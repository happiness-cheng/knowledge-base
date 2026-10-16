# 索引测试为什么改用临时 HTTP 服务

## 真实问题

2026-10-15 和 10-16 的完整回归各出现一次 `Error finding id`，位置均在笔记替换测试的**更新前**：已经写入的记录调用 `get(include=["documents", "metadatas", "embeddings"])` 失败。单文件重复通过和下一次全量通过，不能证明问题已解决。

10-16—17 将相同公共 API 调用抽离业务代码，确认 Chroma 1.5.9 的 EphemeralClient 在集合缓存压力下会出现：文档和 metadata 仍在，读取 embedding 报错，无过滤 query 返回空。并不是本次“缩短笔记删除旧尾块”逻辑删除了其他笔记。

## 可证伪的对照

先写入并读取保留集合的三个向量，再向 512 个新集合各写一条合成向量，最后读取保留集合。没有真实模型、原数据库、原索引或外网调用。

| 连接方式 | 压力前 | 压力后 |
|---|---|---|
| SDK EphemeralClient | 3 个向量可读、query 返回 3 个 ID | metadata 保留 3 个 ID；embedding 报 `Error finding id`，query 空 |
| SDK PersistentClient，默认同步阈值 | 正常 | metadata 保留；向量读取报 `Nothing found on disk` |
| SDK PersistentClient，阈值降为 1 | 正常 | 本机出现 `Error loading hnsw index`，因此未采用此方案 |
| 独立临时 Chroma 服务 + HttpClient | 正常 | 原 3 个向量及 query 结果保持不变 |

另一控制实验：相同两用户写入序列重复 500 轮，诊断进程把 SDK 推导的 HNSW 缓存容量设为 1 时发生 18 次失败；设为 65536 时为 0。这个实验支持缓存淘汰相关的判断，但不是生产容量承诺，更不构成“只要调大缓存就修复”的证据。

本机持久库的 `Error loading hnsw index` 尚未继续定位，不能把它与内存缓存问题直接归为同一根因。没有修改第三方库，也没有切换依赖版本。

[结构化观察记录](evidence/index-cache-boundary-20261017.json)。数据为合成文本、固定 4 维向量；不测语义召回和答案质量。

## 修正与取舍

生产代码原本就要求 API/worker 连接同一个显式 HTTP 服务。之前真实索引测试却使用共享进程内系统的 EphemeralClient，集合名独立不等于底层存储独立。本次只改测试边界：

- 在 pytest session 内启动绑定 `127.0.0.1`、随机端口、临时数据目录的真实 Chroma 服务。
- 每个测试仍用唯一集合名，客户端退出时关闭，session 结束时终止自己启动的服务；启动失败让测试报错，不回退内存库。
- 保留向量值、正文、metadata、用户隔离和故障重放断言；新增上面的 512 集合回归，修正前已实际失败。
- 没有添加重试，也没有移除 embedding 断言或修改业务写入逻辑。

代价是测试要启动本机子进程，较内存模式慢；收益是测试覆盖与已选择的生产存储协议一致。HTTP 模式本次在 512 集合规模下通过，不代表缓存任意容量、重启恢复、长期负载或全部平台均已验证。

官方源码依据：[SharedSystemClient §_get_identifier_from_settings](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/api/shared_system_client.py)、[RustBindingsAPI §__init__/start](https://github.com/chroma-core/chroma/blob/1.5.9/chromadb/api/rust.py)、[LocalSegmentManager §get_hnsw_reader/get_hnsw_writer](https://github.com/chroma-core/chroma/blob/1.5.9/rust/segment/src/local_segment_manager.rs)、[LocalHnswSegmentReader §from_segment](https://github.com/chroma-core/chroma/blob/1.5.9/rust/segment/src/local_hnsw.rs)。源码解释与本机实测共同支持判断，不将上游相似 issue 当作本项目根因证明。

## 实际验证

在已有约束环境、backend 目录运行：

```text
python -X utf8 -m eval.offline_tests --empty-model-cache tests/test_rag_index_updates.py::test_other_collections_do_not_make_an_existing_nodes_vectors_unreadable -q --tb=short
# 修正前：1 failed，3.80s，Error finding id
python -X utf8 -m eval.offline_tests --empty-model-cache tests/test_rag_index_updates.py tests/test_embedding_input_budget.py tests/test_index_worker_chroma.py -q --tb=short
# 修正后：30 passed，22.37s
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
# 修正后：441 passed，5 条既有 warnings，78.51s
python -m ruff check tests/conftest.py tests/test_rag_index_updates.py tests/test_embedding_input_budget.py
# All checks passed!
```

7 个既有工程模块的 mypy、改动文件编译和 artifact policy 均通过。没有修改前端，未重复前端构建；历史 440 项记录保留其原时间点，本次增加 1 个回归。没有执行原库迁移、线上部署、模型请求或原索引操作。
