# Knowledge Base：使用与复现

项目概览、当前结果和代码阅读路线见[仓库首页](README.md)。本页说明如何安装、启动与验证；历史文档保留当时的实验状态。

## 1. 先运行隔离回归

已验证 Windows / CPython 3.12.15。项目根目录：

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements.txt -c backend/constraints.verified-win-py312.txt
.venv/Scripts/python.exe -m pip install pytest httpx ruff mypy -c backend/constraints.verified-win-py312.txt
cd backend
../.venv/Scripts/python.exe -X utf8 -m eval.offline_tests --verify-isolation
../.venv/Scripts/python.exe -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
```

当前本地 440 项通过；无需个人配置、在线模型或原数据库。约束文件固定已验证的 Windows 环境版本，不是跨平台、带文件 hash 的依赖 lock。直接 `pytest` 不具有离线入口的配置隔离承诺。

## 2. 启动一个新的本机实例

以下步骤只面向自己的新状态目录；现有实例应先做迁移与索引计划。配置通过环境变量提供，或参考仓库 `env.template` 自行准备本地配置；凭据不入库。模型服务使用 Anthropic Messages 兼容协议，不能仅把 OpenAI Chat Completions 地址填进来。

### Chroma 存储服务

在已安装依赖的环境中，选独立绝对路径启动：

```powershell
.venv/Scripts/chroma.exe run --path "$env:TEMP/kb-demo-chroma" --host 127.0.0.1 --port 8011
```

API 和 worker 共享 `http://127.0.0.1:8011`。复现过 Chroma1.5.9 的跨进程 PersistentClient query 陈旧问题，因此独立 worker 不与在线 API 直接读写同一持久目录；详情见[进程边界](docs/2026-10-14-chroma-process-boundary.md)。

### SQL 与 API

在项目 `backend` 目录的新终端，按自己的目录设置：

```powershell
$env:APP_ENV = 'development'
$env:ENV_FILE = 'absent-demo.env'
$env:DATABASE_URL = 'sqlite:///C:/temp/kb-demo/knowledge.db'
$env:KB_CHROMA_URL = 'http://127.0.0.1:8011'
$env:KB_CHROMA_DIR = 'C:/temp/kb-demo/worker-lock'
$env:UPLOAD_DIR = 'C:/temp/kb-demo/uploads'
```

先创建 `C:/temp/kb-demo` 等你选择的父目录，再对**这个新库**显式执行：

```powershell
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

production 配置要求非默认且至少32字符的 `SECRET_KEY`、合法 Fernet `AI_KEY_ENCRYPTION_KEY`、显式 `KB_CHROMA_URL`；校验失败拒绝启动。需要生成/分析时，调用者显式配置 `AI_API_KEY`、兼容的 `AI_BASE_URL` 与 `AI_MODEL_NAME`。代码默认不读取个人工具配置；离线回归无需这些凭据。

### 独立索引 worker

在相同环境、`backend` 目录启动：

```powershell
../.venv/Scripts/python.exe -m app.services.index_worker --database-url 'sqlite:///C:/temp/kb-demo/knowledge.db' --chroma-url 'http://127.0.0.1:8011' --lock-dir 'C:/temp/kb-demo/worker-lock'
```

`--lock-dir` 必须绝对路径，同一主机所有 writer 使用同一路径。生产配置禁止本地回退；本地目录模式只允许停 API 后用 `--offline-local` 显式离线更新。worker处理持久任务，API可查询索引状态；就绪接口为 `/api/ready`，依赖失败503。首次 embedding 需要调用者自行准备 BGE 模型；不要把模型下载时间计为稳态检索延迟。

### 前端

在项目 `frontend` 目录：

```powershell
npm ci
npm run dev
```

开发页面默认5173，经 Vite 代理访问8766 API。生产静态产物用 `npm run build`；API支持显式 `KB_FRONTEND_DIST`。当前前端构建已验证，容器镜像构建与公网部署未作为本次结果。

## 3. 运行真实缓存模型实验

题集与语料清单在 `backend/eval/fixtures/`，每篇语料按 SHA256 校验。先自行准备指定 BGE / reranker snapshot；脚本缺缓存直接失败，不联网补齐。在 `backend` 目录运行：

```powershell
# 固定/标题切片三方案；--prepare 只校验题集和切片，不编码
../.venv/Scripts/python.exe -X utf8 -m eval.run_slice_comparison --hf-home '<模型缓存根目录>' --prepare
# 去掉 --prepare 会真实编码，当前CPU约20分钟

# BM25/dense/RRF与reranker匹配对照
../.venv/Scripts/python.exe -X utf8 -m eval.run_retrieval_matrix --hf-home '<模型缓存根目录>' --device cpu --threads 4

# 上下文预算/邻居实验，使用自己上一条产生的K3目录
../.venv/Scripts/python.exe -X utf8 -m eval.run_context_matrix --baseline '<K3输出目录>' --hf-home '<模型缓存根目录>'
```

首次模型推理的成本与缓存评分后的打包时间分开；BGE证据token不是生成模型完整提示token。受控改写是固定别名诊断，不能当作真实LLM改写收益。更多结果与负例见[项目证据](docs/project-evidence.md)。

## 4. 当前边界

API默认自定义Agent；严格 `kb_only` 与 LangChain显式选择，LC检索候选通过 `retrieval_mode` 配置，rerank/rewrite默认关闭。SQL/Chroma最终一致性允许更新期间暂时缺证据；没有跨库原子切换、租约续租或跨主机writer锁。旧数据迁移、旧索引重建、公网鉴权部署、MySQL并发和长期负载需各自验收，不由本机回归推断。
