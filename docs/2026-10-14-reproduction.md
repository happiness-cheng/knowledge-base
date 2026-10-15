# 知识库候选的复现与验收

已在独立Windows / CPython 3.12.15环境运行；不要复用项目旧Python 3.14虚拟环境。项目原数据库、索引、个人配置不属于离线复现输入。前端本轮没有改动或构建验收，以下范围是后端与实验工具。

## 安装

在项目backend目录，使用自己的可用Python 3.12和uv创建隔离环境：

```powershell
uv venv --python 3.12 .venv-verified
uv pip install --python .venv-verified/Scripts/python.exe -r requirements.txt -c constraints.verified-win-py312.txt
uv pip install --python .venv-verified/Scripts/python.exe pytest httpx ruff -c constraints.verified-win-py312.txt
```

`constraints.verified-win-py312.txt`来自本次已运行环境，固定153个已安装发行包的版本，仅约束依赖解析；不是要求全部安装的requirements，也不是带文件hash的跨平台lock。完整环境曾包含未使用的调研依赖，不将它当作最小生产依赖清单。已在当前环境执行requirements+constraints离线dry-run，输出Would make no changes。

## 无模型/无个人配置的回归

```powershell
.venv-verified/Scripts/python.exe -X utf8 -m eval.offline_tests --verify-isolation
.venv-verified/Scripts/python.exe -X utf8 -m eval.offline_tests tests -q --tb=short
.venv-verified/Scripts/python.exe -X utf8 -m eval.run_core_rag_comparison --dry-run
```

本次隔离探针PASS，全回归352 passed / 5 warnings。警告包含既有SQLAlchemy关系/IN写法及anyio断言重写；没有在这次目标之外修正它们。直接运行pytest会触发应用默认配置读取，不具备该入口的个人配置隔离承诺。临时内存SQL/Chroma与socket外网阻断不等于隔离任意子进程网络的沙箱。

## 本地模型实验

本次只读已有`D:/AI_Models/huggingface`缓存，无下载。需要BAAI/bge-large-zh-v1.5与BAAI/bge-reranker-v2-m3的已缓存snapshot；缺失时脚本失败，不联网补齐。实际CPU完整矩阵较慢：221块编码约425秒，精排720pair约36×35秒量级。参数、revision、hash、时间口径见[检索矩阵](2026-10-13-retrieval-matrix.md)。

```powershell
.venv-verified/Scripts/python.exe -X utf8 -m eval.run_retrieval_matrix --device cpu --threads 4
.venv-verified/Scripts/python.exe -X utf8 -m eval.run_context_matrix
```

相邻块脚本默认复用本次K3报告路径；换机器或重新运行时用`--baseline`指定刚产生的输出目录。必须保留16篇选定语料、题集、chunk-manifest和K3报告；它们不是个人原数据库。

## API与当前边界

现有认证chat API仅在`kb_only=true, backend=langchain`启用候选，retrieval_mode可选current/dense/bm25/hybrid，rerank/rewrite默认关闭。候选在当前SQL归属、节点存在与正文新鲜度核验之后检索，最多读取5000索引块。BGE预算不是LLM的完整输入token预算；匹配提供方token counter未接入时，模型调用按字符硬上限保护。

新切分尚未迁移既有索引；超512块会被生产候选拒绝，不能宣称已有全部笔记索引自动升级。K0保证串行更新失败可重放，仍没有版本化原子切换、并发协调或持久任务outbox。

真实有限模型对照尝试与外发授权记录见[在线验收](2026-10-14-online-rag-validation.md)，当前不能报告真实回答正确率。未部署生产、未提交或推送。
