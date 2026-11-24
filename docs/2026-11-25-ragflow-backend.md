# RAGFlow 检索/存储后端：接入与运行

- 日期：2026-11-25
- 目标版本：RAGFlow v1.0.0（HTTP API）
- 决策记录：[ADR 0002](adr/0002-ragflow-backend.md)
- 状态：代码/单元测试已接入；真实 RAGFlow 冒烟待 Docker daemon 可用后执行

## 1. 它替换了什么

| 层 | 之前 | 接入 RAGFlow 后 |
|---|---|---|
| 文档解析/切片 | `split_by_headings` + `prepare_chunks` | RAGFlow parser（`parse_type=1, parser_id=general`） |
| 向量存储 | Chroma HTTP | RAGFlow dataset / 文档引擎 |
| 混合检索 | 自研 dense/BM25/RRF | RAGFlow `/api/v1/retrieval` |
| 索引任务 | `index_jobs` + Chroma writer | `index_jobs` + RAGFlow 上传/解析 worker |
| 笔记真值 | SQL | 仍是 SQL；RAGFlow 是可重建派生索引 |
| 引用契约 | `[doc:node_id]` | 仍由 SQL `node_id` + `finalize_kb_answer` 校验 |

## 2. 启动 RAGFlow

RAGFlow 1.0 需要其官方 Docker Compose（RAGFlow、文档引擎、MySQL、MinIO、Redis 等）。
以官方 Quickstart 为准：

```powershell
git clone --depth 1 --branch v1.0.0 https://github.com/infiniflow/ragflow.git
cd ragflow/docker
docker compose -f docker-compose.yml up -d
```

启动后在 RAGFlow UI 创建 API Key，并确认服务地址（默认 `http://127.0.0.1:9380`；
容器内访问宿主机可用 `http://host.docker.internal:9380`）。

> 本机当前 Docker daemon 未运行，且磁盘余量有限；因此本轮没有执行真实 RAGFlow
> 冒烟。不要把这部分写成“已在线验证”。

## 3. 配置本应用

复制 [env.template](../env.template) 为 `.env`，至少设置：

```dotenv
APP_ENV=production
DATABASE_URL=mysql+pymysql://...
SECRET_KEY=<32+ 字符>
AI_KEY_ENCRYPTION_KEY=<Fernet key>

KB_RETRIEVAL_BACKEND=ragflow
RAGFLOW_BASE_URL=http://host.docker.internal:9380
RAGFLOW_API_KEY=<RAGFlow API Key>
RAGFLOW_DATASET_PREFIX=kb_user
RAGFLOW_TIMEOUT_SECONDS=30
RAGFLOW_EMBEDDING_MODEL=
```

`RAGFLOW_EMBEDDING_MODEL` 留空表示使用 RAGFlow 服务端默认 embedding；不要在同一个
dataset 里混用不同模型。

## 4. 迁移与启动

```powershell
cd backend
python -m alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8766
```

另开终端启动 RAGFlow 模式 worker：

```powershell
cd backend
python -m app.services.index_worker `
  --database-url "mysql+pymysql://..." `
  --ragflow `
  --lock-dir "C:/temp/kb-index-lock"
```

`--ragflow` 模式不需要 `KB_CHROMA_URL`/Chroma 目录；它仍使用同一把单 writer 文件锁，
并轮询 RAGFlow 解析状态（`--refresh-interval`，默认 15 秒）。

## 5. 冒烟与状态

真实冒烟（会创建临时 dataset，结束后默认清理）：

```powershell
cd backend
python -m scripts.ragflow_smoke
```

成功输出包含 `status=ok`、dataset/document id、chunk 数量和 top chunk。

用户级状态：

```text
GET /api/index-jobs/status
```

返回 job 计数、失败 job、RAGFlow dataset、文档状态分布、失败文档。加
`?probe_health=true` 才主动请求 RAGFlow 健康检查，避免状态页默认阻塞。

## 6. 同步语义

1. 保存/更新笔记时，现有路由在同一 SQL 事务登记 `index_jobs`。
2. worker 领取任务后：
   - 按用户创建/复用 dataset `kb_user_{id}`；
   - 内容 fingerprint 未变且状态可检索 → 幂等返回；
   - 内容变化 → 删除旧 document → 上传 `node-{id}.md`；
   - PATCH `meta_fields` 写入 `node_id`、`source_fingerprint`、`title`；
   - 触发解析，本地记录 `ragflow_documents.state=parsing`。
3. worker 周期调用 `refresh_states`，按 RAGFlow `run` 状态更新
   `parsing/ready/failed/missing`。
4. 检索时：
   - 调 `/api/v1/retrieval`；
   - 用 `document_id` 映射回 `ragflow_documents.node_id`；
   - 用当前 SQL 正文重新算 fingerprint，拒绝旧文档；
   - RAGFlow chunk 可能带上传时加的标题前缀，不保证是 `node.content` 的字面子串；
     适配器返回 `source_fingerprint` + `evidence_verified`，共享 `row_is_current`
     只在该凭据与当前 SQL 正文一致时放行；
   - 再交给现有 `AuthenticatedKBRetriever`/`finalize_kb_answer` 做 owner、版本、引用校验。

## 7. 失败与回退

| 情形 | 行为 |
|---|---|
| RAGFlow 未配置 | `run_langchain_rag` 返回 `retrieval_backend_not_configured`；`/api/ready` 503 |
| RAGFlow 不可用 | 聊天返回 retrieval error；不静默回退 Chroma |
| 解析失败 | `ragflow_documents.state=failed`，`/api/index-jobs/status` 可见；可重试 index job |
| 文档缺失 | `state=missing`；重建索引修复 |
| 内容已改但未同步 | 检索 fingerprint 不一致 → 跳过旧 chunk，不用旧证据回答 |
| 需要回退 | `KB_RETRIEVAL_BACKEND=chroma`；RAGFlow 表保留，不删 SQL 笔记 |

## 8. 尚未完成

- 真实 RAGFlow 冒烟与 36 题检索对照（Docker daemon 未运行）。
- RAGFlow 租户/权限模型：当前是服务端单 API Key + 每用户 dataset 命名隔离。
- 大规模 dataset 清理、快照/备份策略：优先使用 RAGFlow 自身的备份能力，本应用只
  保存映射。
- 解析失败自动重试策略：当前复用 `index_jobs` 的有限重试，未单独补偿 RAGFlow 解析
  任务。