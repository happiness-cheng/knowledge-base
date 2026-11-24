# ADR 0002：以 RAGFlow 作为生产检索/存储后端

- 状态：已接受（用户选择）
- 日期：2026-11-25
- 相关计划：`docs/superpowers/plans/2026-11-25-retrieval-storage-hardening.md`
- 目标版本：RAGFlow v1.0.0 HTTP API

## 背景

用户明确最看重在线 RAG 检索和离线存储，并允许重构整个项目。继续维护 Chroma +
自研混合检索/索引任务，无法证明“生产级检索与存储”。因此选择 RAGFlow 作为
文档解析、切片、向量存储和混合检索的生产底座。

## 决策

1. **RAGFlow 是派生索引，不是笔记真值**。SQL 仍保存笔记、标签、图谱、权限和
   `source_fingerprint`；RAGFlow 的数据集/文档可以重建。
2. **每个用户一个 RAGFlow dataset**（`kb_user_{id}`），服务端使用单个 API Key；
   前端不接触 RAGFlow。
3. **一条笔记一个 RAGFlow 文档**（`node-{id}.md`）。内容变化时删除旧文档再上传，
   因为 RAGFlow 1.0 的 PATCH 只改配置，不支持替换文件正文。
4. **同步走现有 `index_jobs`/worker**：save 笔记与登记任务同事务；worker 以
   `--ragflow` 模式调用上传/解析，解析状态由 `ragflow_documents.state` 跟踪。
5. **检索适配器保留 SQL 复核**：RAGFlow chunk 的 `document_id` 映射回 `node_id`，
   再用当前 SQL 正文计算的 fingerprint 校验；不信任 document_id 代表新内容。
6. **功能开关**：默认仍是已验证的 Chroma；`KB_RETRIEVAL_BACKEND=ragflow` 显式启用。
   这样线上可以回退，测试不需要 RAGFlow。
7. **HTTP 直连，不用官方 Python SDK**：`ragflow-sdk==1.0.0` 要求 Python
   `>=3.13,<3.14`，与项目 3.12 验证环境不兼容；客户端只依赖 `httpx`，按 v1.0.0
   REST API 实现并用 MockTransport 测试。

## 数据流

```text
React 保存笔记
  → SQL 保存 + 同事务 index_jobs
  → worker --ragflow
     → ensure dataset（每用户）
     → delete old document（若内容变化）
     → upload node-{id}.md
     → PATCH meta_fields(node_id, source_fingerprint)
     → POST /chunks 触发解析
     → ragflow_documents(state=parsing)

聊天
  → LangChain 严格 RAG
  → ragflow_retrieval.retrieve_for_user
     → POST /api/v1/retrieval
     → document_id → ragflow_documents.node_id
     → SQL 当前正文 fingerprint 复核
  → 现有 AuthenticatedKBRetriever 再验 owner/版本
  → finalize_kb_answer
```

## 后果

正面：

- 文档解析、切片、embedding、混合检索、rerank 交给生产项目；
- 离线存储有 RAGFlow 的数据库/对象存储/索引层，不再维护 Chroma 进程边界；
- 检索链路少一大段自研 BM25/RRF 代码；
- 解析状态、失败、缺失可在 `/api/index-jobs/status` 查看。

代价与限制：

- 需要 Docker 多容器（RAGFlow 1.0 官方 compose：RAGFlow、文档引擎、MySQL、
  MinIO、Redis 等）；本机 Windows daemon 未运行，已在 WSL Docker 上冒烟。
- 2026-11-25 的冒烟只验证 HTTP/队列/状态链路，使用确定性测试向量桩，不是真实
  embedding；真实模型和检索质量仍待验证。
- 解析是异步的；`index_jobs` 成功只代表 RAGFlow 接受上传/解析，不代表 chunk 已可用；
  `ragflow_documents.state` 才是可检索状态。
- 内容更新是 delete+re-upload，document_id 会变化；旧 chunk 的清理依赖 RAGFlow
  删除语义。
- 每个用户一个 dataset，dataset 数量随用户增长；RAGFlow 的租户/权限模型尚未接入，
  当前用服务端单 Key + 数据集命名隔离。
- RAGFlow 不可用时，聊天返回 retrieval error；`/api/ready` 返回 503，不静默回退
  Chroma（避免混用两个索引）。
- RAGFlow 默认 embedding/parser 由服务端配置决定；`RAGFLOW_EMBEDDING_MODEL` 留空
  表示使用服务端默认，不能把“维度相同”当成模型一致。

## 回退

- `KB_RETRIEVAL_BACKEND=chroma` 即回到已验证的 Chroma 路径；RAGFlow 表保留但不再写入。
- 删除 RAGFlow 绑定不会删除 SQL 笔记；重建 RAGFlow 索引只需重新扫描 SQL 节点。

## 验收

- 单元测试：客户端信封/错误、同步幂等/内容变更/失败状态、检索映射/指纹/跨用户、
  配置校验、状态 API。
- 集成冒烟：`python -m scripts.ragflow_smoke`；2026-11-25 已在 WSL Docker 的
  RAGFlow v1.0.0 上跑通，但使用确定性测试向量桩，真实 TEI/BGE 模型未验证。
- 真实 36 题检索对照：待真实 embedding 就绪后，用同一题集比较 Hit@k/证据覆盖；
  未完成前不宣称 RAGFlow 检索质量优于 Chroma。