# 核心 RAG 检索候选与本地矩阵

题集在 2026-10-13 冻结，实际 CPU 测量在 2026-10-14。输入是 16 篇已有技术笔记、36 题（27 正例 / 9 负例），生成者读过原文，因此不称独立盲测。development 为 17 题，heldout 为 19 题；参数只根据 development 选择。没有修改冻结题目、gold 或原笔记。

本轮是 retrieval-only：没有调用 LLM，没有测答案正确率、负例拒答质量、生成 token 或费用收益。完整对照使用同一套 chunk、同一查询、同一 1536 BGE-token 上下文预算。dense 为精确归一化向量内积，不是 Chroma / HNSW ANN 测试。

## 实现与边界

- `backend/eval/retrieval_candidates.py` 提供实际 tokenizer 切片、dense、成熟 `rank_bm25.BM25Okapi`、jieba、按排名的 RRF、上下文打包及可关闭精排。
- 标题方案复用原纯 utils 的缩进 `##` 规则；禁用其二次切片的字符回退，再由实际 BGE fast tokenizer 的 offset mapping 切窗口。模块不导入 app、模型或数据库。
- 每块重新编码完整 `title + heading + body + special tokens` 并核验不超过 512。正文预算为 256 / 384 / 480，overlap 为 0 / 32；正文窗口不足时按真实前缀成本收缩。没有使用字符估算代替真实 token。
- chunk ID 由用户、文档、位置、配置与内容生成，稳定且可去重。授权用户过滤发生在 dense 打分、BM25 词频拟合、融合和精排之前。RRF 使用 `sum(1 / (k + rank))`，不相加不同检索器原始分数。
- 上下文按完整文本真实计数，不能容纳的块跳过，保留跳过数；不截掉正文来伪造 gold 覆盖。报告中的 `retrieved` 是最终预算内的上下文，原候选池的文档 Recall 和 chunk ID 另放逐题 steps。
- 精排可关闭；第三方预测失败显式标记 `degraded` 并保留基础顺序，不冒充成功。20 候选真实评分一次后派生 5 / 10 / 20；关闭精排的匹配候选数控制单独保存。

## 已缓存模型与运行来源

模型仅从 `D:/AI_Models/huggingface` 的现有 snapshot 读取，`local_files_only=True`，HF offline 开启，socket connect / connect_ex 均禁止。没有下载模型、加载 `.env`、读取真实数据库或外发笔记。

| 项目 | 本次设置 |
|---|---|
| embedding | BAAI/bge-large-zh-v1.5，1024 维，归一化，模型最大 512 |
| embedding snapshot | `79e7739b6ab944e86d6171e44d24c997fc1e0116` |
| reranker | BAAI/bge-reranker-v2-m3，真实预测最大 512 |
| reranker snapshot | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` |
| 设备 / 线程 | CPU / Torch 4 线程 |
| batch size | embedding 8；reranker 4 |
| 查询 prefix | 为这个句子生成表示以用于检索相关文章： |
| 固定上下文预算 | 1536 BGE tokens；不等于已测 LLM 提示 token |
| dataset SHA256 | `c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a` |
| corpus manifest SHA256 | `8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b` |

K3 原输出：`backend/eval/reports/retrieval-matrix/20261014T044942416805Z/`。纠正精排预算后，从已校验的真实 K3 候选继续 K4：`20261014T045858911951Z/`。候选数匹配的关闭精排控制：`20261014T050706279477Z/`。

续跑会验证题集 / manifest hash、全部 case ID 与问题，并用相同实际 tokenizer / 原文 / 切片配置重建全部 chunk 记录逐一比较；不会重新编码已完成的 embedding。原执行代码 hash、续跑代码 hash 和控制后处理 hash 分开保留。没有删除先前失败或中止输出。

## K1：已完成 oracle，完整检索对照仍为 partial

全部 12 个方案验证块数、完整输入 token 上限与同块证据可覆盖性。以下是 oracle：检查遍历所有块是否能找到必需证据，不是检索 Recall。

| 策略 / 正文预算 / overlap | 块数 | 最大完整输入 token | development 区间覆盖 | development 整题齐全 | heldout 区间覆盖 |
|---|---:|---:|---:|---:|---:|
| fixed / 256 / 0 | 307 | 270 | 19/25 | 9/15 | 6/17 |
| fixed / 256 / 32 | 348 | 270 | 17/25 | 9/15 | 11/17 |
| fixed / 384 / 0 | 208 | 398 | 20/25 | 10/15 | 14/17 |
| fixed / 384 / 32 | 225 | 399 | 22/25 | 12/15 | 14/17 |
| fixed / 480 / 0 | 170 | 495 | 20/25 | 10/15 | 16/17 |
| fixed / 480 / 32 | 177 | 494 | 21/25 | 11/15 | 16/17 |
| heading / 256 / 0 | 359 | 278 | 21/25 | 12/15 | 8/17 |
| heading / 256 / 32 | 386 | 278 | 21/25 | 11/15 | 11/17 |
| heading / 384 / 0 | 264 | 405 | 24/25 | 14/15 | 14/17 |
| heading / 384 / 32 | 272 | 405 | 24/25 | 14/15 | 14/17 |
| heading / 480 / 0 | 221 | 501 | 25/25 | 15/15 | 13/17 |
| heading / 480 / 32 | 223 | 501 | 25/25 | 15/15 | 16/17 |

选择规则是 development 整题齐全数、区间覆盖率、较少块数，平局优先 heading。本轮选 `heading / 480 / overlap0`。虽然 overlap32 在 heldout 更好，也保留原选择；不能看完预留结果后再切换参数。只对选择后的 221 块跑完整真实检索，未对 12 种方案全部做 embedding / 检索 A/B，所以 K1 不称完整验收。

## K3：同块 dense / BM25 / RRF 真实对照

RRF 的 k 候选为 20 / 60 / 120，只根据 development 上下文证据齐全、区间覆盖、文档 Recall 选择；同分靠近 60。最终 k=60。文档 Recall 按去重父文档计算且为逐题 macro，证据比例为所有必需区间的 micro；正例分母包括执行失败，负例不进入这两类分母。

| 方案 | 全部27正例：区间覆盖 | 全部：整题齐全 | development：区间 / 整题 | heldout12正例：文档 Recall@3 | heldout：区间 / 整题 |
|---|---:|---:|---:|---:|---:|
| dense | 34/42 | 20/27 | 24/25；14/15 | 0.9583 | 10/17；6/12 |
| BM25 | 33/42 | 19/27 | 23/25；13/15 | 0.9583 | 10/17；6/12 |
| RRF | 35/42 | 21/27 | 24/25；14/15 | 1.0000 | 11/17；7/12 |

三组均 36 个有效用例、0 invalid gold、0 execution error。全部正例 Hit@3 都是 1，但证据覆盖不同：命中文档不代表拿到完整答案区间。当前小样本里 RRF 有增益，不能据此推出全部真实问题、线上用户或其他切片方案都优于 dense。

## K4：真实精排完成，默认保持关闭

以相同 RRF 前20候选预测真实 pair 分数，再按原候选前5 / 前10 / 前20分别重排和消费同一预算。匹配的 `rrf_off_5/10/20` 控制复用相同候选池；不能只把 rerank5 与 off20 比较后称为精排收益。

真实20-pair预测记录与缓存消费时间分开：首次预测实测 34.405 秒，随后每题约30–41秒。`cache_filter_sort_ms` 仅是消费缓存分数的排序时间；不会当作 reranker 推理毫秒。pool5/10 没有分别重新预测，无法报告它们独立的真实推理延迟。pair 截断目前按共同20候选统计。

最终 checkpoint 为36/36，720个真实pair，0截断、0降级、0执行错误。20-pair推理最小23.188秒、中位35.197秒、最大45.488秒；不是线上端到端时延。

| 相同候选数 | 全27正例区间 off→on | 全27正例整题 off→on | development 区间 off→on | heldout 区间 off→on | heldout 整题 off→on |
|---|---:|---:|---:|---:|---:|
| 5 | 35/42→36/42 | 21/27→22/27 | 24/25→25/25 | 11/17→11/17 | 7/12→7/12 |
| 10 | 35/42→35/42 | 21/27→22/27 | 24/25→25/25 | 11/17→10/17 | 7/12→7/12 |
| 20 | 35/42→36/42 | 21/27→22/27 | 24/25→25/25 | 11/17→11/17 | 7/12→7/12 |

本次开发集有微小提升，预留集没有完整证据收益，候选10还丢失一个证据区间。结合已测CPU成本，生产候选保留rerank开关，默认关闭。不能把引入精排本身写成已提升回答准确率。

## K5：相邻块与预算真实对照

新增`eval/context_candidates.py`和`eval/run_context_matrix.py`。复用K3前20候选，校验dataset、manifest、tokenizer revision、按原文重建的全部221块及逐题问题，无需再次编码或精排。按源顺序取同用户、同文档的前后各一块，anchor→previous→next，去重后消费相同预算，保留完整块。1536/off控制与K3最终chunk ID逐题一致。

| BGE证据预算 / 邻居 | 全27正例区间 / 整题 | development 区间 / 整题 | heldout 区间 / 整题 |
|---|---:|---:|---:|
| 1024 / off | 35/42；21/27 | 24/25；14/15 | 11/17；7/12 |
| 1024 / on | 31/42；17/27 | 21/25；11/15 | 10/17；6/12 |
| 1536 / off | 35/42；21/27 | 24/25；14/15 | 11/17；7/12 |
| 1536 / on | 33/42；19/27 | 23/25；13/15 | 10/17；6/12 |
| 2048 / off | 37/42；22/27 | 25/25；15/15 | 12/17；7/12 |
| 2048 / on | 36/42；21/27 | 24/25；14/15 | 12/17；7/12 |

开发集规则选2048/off，但尚未据此改生产默认1536：计数是证据BGE token，不含实际LLM系统提示/问题/schema，未测更长上下文的生成成本与正确率。邻居固定预算下会挤占其他证据，因此未接入生产索引；接入前还需持久源位置元数据。这只是一个邻居排列策略的结果，不代表所有邻居方案都差。

结果位于`backend/eval/reports/context-matrix/20261014T091908931513Z/`，6方案×36题均无执行错误。命令：`python -m eval.run_context_matrix`。相邻块契约4用例通过；脚本初次复用manifest缺少user_id失败，加入冻结服务端owner后实际运行成功，未改gold、语料或原索引。

## 时间口径与验证

221 块编码实测 424.706 秒。最初总时长估计5–15分钟偏低，观察到约20秒 / embedding batch 后修正；精排20pair首批34.405秒后，再估计36题约20分钟。估计不是测量，最终以逐题 checkpoint 和完整报告为准。

模型加载与首次预测分开记录；这里的“冷”指新进程首次加载 / 首批推理，没有清空操作系统磁盘缓存。报告 `latency_ms` 是实测 query 编码、context packing、共同20pair预测（启用时）的分段加总；不包含模型加载 / 建索引，也未计入候选打分阶段，不是完整线上响应延迟。缓存消费毫秒另列。不能把这些数字写成应用线上 p95。

TDD 记录：候选函数 9 failed → 9 passed；脚本选择 / oracle 3 failed / 9 passed → 12 passed；短末节 1 failed / 12 passed → 13 passed；精排 token 限额回归 1 failed / 13 passed → 14 passed；匹配关闭控制 1 failed / 14 passed → 15 passed。最新版三个 Python 文件 Ruff 为 All checks passed。负例拒答、LLM答案和token收益未测。

真实运行在 backend 目录：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\生产工程实施-20261013\env-clean\Scripts\python.exe' -X utf8 -m eval.run_retrieval_matrix --device cpu --threads 4 --embedding-batch-size 8 --rerank-batch-size 4
```

后续只续真实 K3 候选的 K4：

```powershell
python -m eval.run_retrieval_matrix --resume-k3 eval/reports/retrieval-matrix/20261014T044942416805Z --device cpu --threads 4
python -m eval.run_retrieval_matrix --resume-k3 eval/reports/retrieval-matrix/20261014T044942416805Z --disabled-only
python -m eval.offline_tests tests/test_retrieval_candidates.py tests/test_core_corpus.py tests/test_benchmark.py -q --tb=short
python -m ruff check eval/retrieval_candidates.py eval/run_retrieval_matrix.py tests/test_retrieval_candidates.py
```

本轮候选只用于离线矩阵；应用接入由主任务单独处理。未修改 rag_service、LC/chat、requirements、数据库 schema、索引集合或用户配置。
