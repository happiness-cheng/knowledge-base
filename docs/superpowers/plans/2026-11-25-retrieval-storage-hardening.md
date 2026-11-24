# 在线检索与离线存储加固计划

> **2026-11-25 更新**：用户选择直接接入 **RAGFlow v1.0**，主线改为
> [ADR 0002](../../adr/0002-ragflow-backend.md) 与
> [RAGFlow 接入说明](../../2026-11-25-ragflow-backend.md)。本文件中 Chroma HTTP
> 对账/状态 API 的部分保留为 fallback；RAGFlow 负责解析、切片、向量存储和混合检索。

- 日期：2026-11-25
- 状态：已根据用户优先级调整；Ragas / Langfuse / LangGraph / Docling 暂停
- 目标：把“能搜得准”建立在两个可验证的前提上：
  1. **离线索引与 SQL 真值一致、可对账、可修复**；
  2. **在线检索每一阶段可观察、可回归、可解释**。

## 0. 为什么调整

用户明确最看重在线 RAG 检索和离线存储，因为这是检索准确性的前提。原计划中的 Ragas、Langfuse、LangGraph、Docling 都改为支撑项，不抢主线。

当前项目已经具备的基础：

- 默认对话已统一为 LangChain 严格 RAG + dense 检索；rerank/rewrite 显式 opt-in。
- `index_jobs` 有 generation、CAS 租约、有限重试；独立 worker 通过 Chroma HTTP 写入。
- `retrieval_pipeline` 有 dense/BM25/RRF/rerank 候选，但默认不启用混合检索。
- `eval/index_audit.py` 能做只读对账，但它读取 **Chroma SQLite 快照**，而生产使用 Chroma HTTP；它检查的 `source_document_hash` 与生产 metadata 的 `source_fingerprint` 也不是同一个字段。

当前真实缺口：

| 缺口 | 影响 |
|---|---|
| 没有面向 HTTP Chroma 的索引对账 | 生产索引是否缺节点/孤儿/旧块，只能靠人工脚本和 SQLite 快照 |
| 没有 collection 级元数据（模型、维度、切分策略、schema 版本） | 无法判断“这个集合是不是当前 BGE/切分器写的”；旧索引可能被当成新索引 |
| 只有单节点 job 状态，没有用户级索引健康视图 | 失败任务、积压、旧块不可见 |
| 默认 dense 检索没有分阶段 trace | 不知道慢在 embedding、Chroma、SQL 校验还是分组；不知道 freshness 过滤掉了什么 |
| 没有检索质量回归门禁 | 改检索/切分/索引后，只能人工跑矩阵；回归不会被 CI 拦住 |
| hybrid 候选每次加载整集合与 embeddings | 个人库可接受，但线上扩展性差，且容易读到旧快照 |
| `docker-compose.yml` 没有 Chroma/worker/migration | “一键部署”与实际架构不一致，离线存储无法按文档复现 |

## 1. S1：离线存储可信（优先）

### 1.1 collection 元数据与模型身份

- 在 `app/services/rag_service.py` 定义并写入：
  - `schema_version=1`
  - `embedding_model='BAAI/bge-large-zh-v1.5'`
  - `embedding_dimension=1024`
  - `chunk_strategy='heading+prepare_chunks(512)'`
- 新建集合时写入 metadata；读取已存在集合时**不改写**，只校验并报告 `metadata_missing` / `metadata_mismatch`。
- 旧集合的处理：报告为 `needs_verification`，由显式重建/迁移脚本处理；不在请求路径自动改 metadata。

### 1.2 HTTP 索引对账

新增 `backend/app/services/index_reconcile.py`：

```python
def reconcile_user_index(db, user_id, collection, *, max_chunks=5000) -> dict:
    ...
```

输入：

- SQL 当前用户节点：`id, title, content, content_hash`
- Chroma `collection.get(include=['documents','metadatas'])`，有上限，拒绝超限而不是静默截断
- collection metadata

输出（只读）：

```json
{
  "user_id": 1,
  "collection": "user_1_nodes",
  "collection_exists": true,
  "schema_version": 1,
  "indexed_chunks": 84,
  "indexed_nodes": 20,
  "missing_node_ids": [],
  "orphan_node_ids": [],
  "stale_chunk_ids": [],
  "unverifiable_chunk_ids": [],
  "empty_content_node_ids": [],
  "metadata_status": "match",
  "freshness": "verified",
  "health": "healthy",
  "repair_actions": {"upsert_node_ids": [], "delete_node_ids": []}
}
```

判定规则：

- SQL 有、索引无 → `missing`，建议 upsert。
- 索引有、SQL 无 → `orphan`，建议 delete。
- chunk 有 `source_fingerprint` 且与当前 `fingerprint(title, content)` 不一致 → `stale`，建议 upsert。
- chunk 没有 `source_fingerprint` → `unverifiable`，不能算 healthy；建议显式重建。
- SQL 正文为空但索引有块 → `empty_content`，建议 delete。
- collection metadata 缺失/不匹配 → `metadata_missing` / `metadata_mismatch`，`needs_verification`。
- 只有所有块都带指纹且匹配、无缺失/孤儿/空正文，才是 `healthy`。

修复：

- `apply_reconcile(db, report, *, now=None)` 只做两件事：
  - 对 `upsert_node_ids` 调用 `enqueue(..., 'upsert', current_fingerprint)`
  - 对 `delete_node_ids` 调用 `enqueue(..., 'delete', current_fingerprint)`
- 不直接写 Chroma；修复仍走现有 worker/CAS 通道。
- 默认 dry-run；CLI/API 显式 `apply=true` 才登记任务。

### 1.3 索引状态 API

在 `app/routers/index_jobs.py` 增加：

- `GET /api/index/status`
  - job 计数：pending/running/failed/succeeded
  - failed 节点列表（最多 20 条，仅当前用户）
  - collection exists/count
  - collection metadata 状态
  - 不跑全量对账（避免每次请求扫描集合）
- `POST /api/index/reconcile`
  - 默认 `apply=false`，只返回对账报告
  - `apply=true` 时登记修复任务并返回 `enqueued`
  - 仅当前用户；限流；不返回笔记正文，只返回 ID/计数/错误类型

### 1.4 compose 与复现

修正 `docker-compose.yml` 或新增 `docker-compose.demo.yml`：

- `chroma` 服务（HTTP，持久卷，healthcheck）
- `backend` 使用 `KB_CHROMA_URL=http://chroma:8000`
- `index-worker` 与 backend 共享 SQL 与 Chroma，使用同一 lock dir
- 启动前执行 `alembic upgrade head`（init 容器或 entrypoint）
- 保留 MySQL 作为可选 profile；默认 demo 可用 SQLite

### 1.5 测试与验收

- `tests/test_index_reconcile.py`：missing/orphan/stale/unverifiable/empty/metadata；apply 只登记任务；跨用户隔离。
- `tests/test_index_status.py`：job 计数、failed 列表、collection count、无索引时 404/空状态。
- `tests/test_collection_metadata.py`：新集合写入 metadata；旧集合只报告不修改。
- 验收脚本：
  1. 建 3 个节点、索引 5 块；
  2. 删除 1 个节点、改 1 个正文、清空 1 个 metadata；
  3. 对账报告精确列出 missing/orphan/stale/unverifiable；
  4. `apply=true` 后 job 为 pending；
  5. worker 跑完后再对账，状态变为 healthy/needs_verification（旧块无指纹时仍不谎报 healthy）。

## 2. S2：在线检索可信

### 2.1 分阶段 trace

不改变 `retrieve_relevant_nodes` 的返回类型；新增可选 `record_trace: Callable[[dict], None]`：

- `embedding_ms`、`chroma_ms`、`sql_ms`、`total_ms`
- `requested_top_k`、`n_fetch`、`candidate_chunks`
- `ownership_rejected`、`stale_rejected`、`empty_content_rejected`
- `selected: [{node_id, chunk_index, distance, source_fingerprint}]`
- `collection`, `metadata_status`

`run_langchain_rag` 把它放到返回的 `retrieval_trace`；`chat.py` 对默认路径也返回该字段。前端可先不展示，先保证 API/日志可查。

### 2.2 36 题检索回归

新增 `backend/eval/run_retrieval_regression.py`：

- 输入：冻结 36 题、16 篇语料、现有切片/索引
- 指标：Hit@1/3、MRR、evidence coverage、nDCG@10、p50/p95
- 输出：逐题命中/证据区间/失败桶（未命中、命中但证据被挤掉、freshness 拒绝、超预算）
- 基线：`backend/eval/fixtures/retrieval-baseline-20261125.json`
- 门禁：heldout 上 evidence coverage / Hit@3 不得低于基线；下降即失败
- CI：先用确定性 fixture 跑 plumbing；真实 BGE 回归放 manual/nightly，避免每次 PR 下载模型

### 2.3 默认路径的验收

- 默认 dense 路径必须有 trace；响应不因 trace 增加明显延迟（目标 p95 +<20ms）。
- 36 题回归报告能复现当前证据覆盖；任何默认改动都必须附 before/after。
- 失败桶必须能区分“检索没找到”和“找到了但上下文没进去”。

## 3. S3：有测量的检索改进

按以下顺序做，每项都必须用 S2 的 36 题回归做 paired 对照：

1. **query-adaptive hybrid**：dense 先查；当 top1 距离高、查询含 API/数字/中文实体时补 BM25 + RRF。避免每次全量 hybrid。
2. **MMR / 去冗余**：同一 node 内 2 块仍可能重复；比较 evidence coverage 与上下文 token。
3. **检索缓存**：key = user_id + normalized query + index generation；索引任务 enqueue 时失效；测 p50/p95。
4. **rerank**：只有找到更小/更快的模型，且 36 题证据覆盖有净增，才考虑；当前 CPU 20-pair 35s 的结论仍有效。

默认值只在满足以下条件时改变：

- evidence coverage 或 Hit@3 有正收益；
- 没有 heldout 退化；
- p95 延迟在可接受预算内；
- 失败案例能解释。

## 4. S4：评测/可观测作为支撑

- Ragas：等 S1/S2 稳定后，作为“检索/生成”第二视角接入；不进生产依赖。
- Langfuse：如果 S2 的本地 trace 不够用，再接；默认脱敏、故障不阻塞。
- LangGraph/Docling：暂停，除非存储/检索主线需要。

## 5. 时间表

| 周 | 内容 | 产出 |
|---|---|---|
| 第 1 周 | S1 元数据 + HTTP 对账 + 状态 API + 测试 | 可对账、可修复、可观察的索引 |
| 第 2 周 | S1 compose + S2 trace | 一键 demo；默认检索分阶段 trace |
| 第 3 周 | S2 36 题回归 + CI plumbing | 检索质量门禁与失败桶 |
| 第 4 周 | S3 第一项（query-adaptive hybrid 或 cache） | 有 before/after 的默认决策 |

## 6. 明确不做

- 不先接 Ragas/Langfuse/LangGraph/Docling 来“增加简历关键词”。
- 不在没有 36 题对照的情况下改默认检索。
- 不把“维度相同”当成“模型/归一化一致”。
- 不把“对账无差异”写成“ANN/向量完全健康”；仍保留 `needs_verification` 语义。