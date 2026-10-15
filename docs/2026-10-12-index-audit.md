# 只读索引对账

该入口检查显式语料快照与 Chroma metadata SQLite 快照，使用标准库 sqlite3 的 `mode=ro`、`query_only` 和读事务。它不导入应用，不创建缺失集合，不加载模型，不读取 .env，不修复索引，也不默认输出笔记正文。

在 backend 目录执行：

```powershell
python -m eval.index_audit --corpus YOUR_SNAPSHOT.json --chroma-sqlite YOUR_CHROMA_COPY/chroma.sqlite3 --collection YOUR_COLLECTION --output YOUR_NEW_REPORT.json
```

语料格式与统一 benchmark 一致：`{"nodes":[{"node_id":7,"title":"标题","content":"正文"}]}`。必须使用对应用户的快照。诊断只能检查调用者选定的集合，不能替调用者证明快照和集合属于同一个用户。

报告包括数据库有而索引没有的节点、索引孤儿节点、标题差异、缺失或非法块元数据、分块数、维度和存储配置。缺失文件、缺失集合不自动创建；报告不覆盖已有文件或输入文件。当前支持本机所验 Chroma SQLite 的 collections/segments/embeddings/embedding_metadata 列结构；结构不同会明确失败，不能承诺所有 Chroma 版本兼容。

如需逐块对账，先用现有 `split_by_headings` 和相同 tokenizer 离线生成期望块快照：

```json
{"chunks":[{"chunk_id":"7:0","node_id":7,"title":"标题","heading":"小节","document":"块内容"}]}
```

```powershell
python -m eval.index_audit --corpus YOUR_SNAPSHOT.json --chroma-sqlite YOUR_CHROMA_COPY/chroma.sqlite3 --collection YOUR_COLLECTION --expected-chunks YOUR_EXPECTED_CHUNKS.json --output YOUR_NEW_REPORT.json
```

它比较缺块、多块和同 ID 内容/标题/小节差异。使用不同 tokenizer、切分器版本或原文预处理会引入差异；“与当前切分器不一致”不能直接归因为索引过期。报告仅输出块 ID 和 hash，原文仍留在本地输入文件。

`freshness` 只有当块保存了按本工具定义的 `source_document_hash` 才能进行版本比较。当前历史索引未保存该凭据，结果是 unknown。维度相同只能说明维度匹配，不能证明模型型号一致或向量已归一化；metadata 诊断也不验证 ANN 文件、实际 embedding 值和检索质量。因此未发现差异时仍是 `needs_verification`，不会输出误导性的全量 healthy。

退出码：0 表示本次未发现对账差异，但仍可能有未验证项；2 表示发现 unhealthy；1 表示读取/结构失败。宿主 shell 可能将非零命令统一展示为失败，应结合 JSON 的 health/errors 判断。

## 本机 2026-10-12 结果

user4 的关系库快照有 20 条笔记。配置集合 user_4_nodes_prod 为 0 块，诊断 missing 全部 20 个节点、unhealthy。参考集合 user_4_nodes 为 84 块、20 节点、1024 维；与当前生产切分器及缓存 bge tokenizer 生成的 84 块逐一比较未发现差异。但父文档版本凭据、模型身份和归一化仍 unknown。

完整私人快照和原始报告留在仓库外，不随项目发布。没有修复原 MySQL、切换 .env、删除索引或新增模型调用。后续修复应在显示具体范围后单独确认。
