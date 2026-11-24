# 项目证据：从检索问题到可恢复索引

这是当前代码的阅读入口。数据来自本地实际实验与故障注入；模拟题、fixture、真实编码和真实生成分别标注。历史设计记录保留原时间点，不把后续实现倒写为旧实验已具备的能力。

## 1. 切片合规与证据覆盖是两个问题

**触发**：仅限制正文480 token，长标题、小节与特殊token会使完整BGE输入达到565。静默截断可能丢尾部表示。选择按真实tokenizer测完整输入、动态再切，并在encode前校验；相比固定预留更精确，代价是更多向量与标题重复。

[真实tokenizer样本](evidence/embedding-input-budget.json)：565拆成512/138，正文完整保留。本探测未调用encoder；下表才是真实BGE编码检索。

**控制条件**：16篇技术笔记，36题（27正例/9负例），17 development/19 heldout；1024维归一化BGE、精确dense内积、20候选、1536 BGE证据token完整块预算。CPU4线程/batch8；revision `79e7739b6ab944e86d6171e44d24c997fc1e0116`。

| 候选 | 块数 | 最大完整token | 覆盖区间/42 | 整题齐全/27 | dev区间/25；整题/15 | heldout区间/17；整题/12 |
|---|---:|---:|---:|---:|---|---|
| fixed480 | 170 | 495 | 26 | 15 | 16；8 | 10；7 |
| heading384 | 264 | 405 | 36 | 22 | 24；14 | 12；8 |
| heading480 | 221 | 501 | 34 | 20 | 24；14 | 10；6 |

同480策略对照净增8区间，CR09/CR21/CR32各退1；标题策略同时改变边界与前缀。384总体更高，但开发集与480同分、块更多，不利用已看过的heldout再调默认。原始区间结果、655个真实向量及hash见[冻结报告](../backend/eval/reports/slice-comparison/20261014T153425634683Z/summary.json)和[provenance](../backend/eval/reports/slice-comparison/20261014T153425634683Z/provenance.json)。三组块编码分别378.773/401.841/381.994秒，非线上SLA。

最初报告漏标retrieval模式，空回答产生无意义的引用/拒答聚合指标。保留原测量，按同一retrieved/steps/latency重算；这里发布的是修正后的retrieval-only报告，回答聚合指标null。便携入口[run_slice_comparison.py](../backend/eval/run_slice_comparison.py)只改路径/显式缓存参数及模式保护，本次再次验证`--prepare`；完整编码结果来自原测量，未冒充又重跑20分钟。

实验切片候选不是业务切片函数，精确内积不是Chroma ANN；区间覆盖不是生成正确率。题目由读过源文的agent编写，heldout不是独立盲测。

## 2. 检索组件的负结果也决定默认值

**问题**：三个方案文档Hit@3都为1，看上去已足够，但最终上下文仍缺答案。

| 实验 | 必需区间/42 | 实际选择与限制 |
|---|---|---|
| dense / BM25 / RRF | 34 / 33 / 35 | RRF净增1，也有退化；保留显式候选，不把分数量纲直接相加 |
| RRF+reranker pool5/20匹配off/on | 35 → 36，heldout均11/17 → 11/17 | 720真实pair；20pair CPU推理中位35.197s，默认关闭 |
| reranker pool10 heldout | 11/17 → 10/17 | CR17退化；不能用on5与off20混比 |
| 1536预算邻居off/on | 35 / 33 | 当前anchor/邻居顺序挤占其他证据，未默认启用 |
| 2048预算邻居off/on | 37 / 36 | 开发集选择2048/off；未测完整生成提示成本/答案收益 |

来源：[K3报告](../backend/eval/reports/retrieval-matrix/20261014T044942416805Z/k3-rrf.json)、[K4真实评分](../backend/eval/reports/retrieval-matrix/20261014T045858911951Z/k4-score-checkpoint.json)、[匹配off控制](../backend/eval/reports/retrieval-matrix/20261014T050706279477Z/matched-disabled-summary.json)、[K5矩阵](../backend/eval/reports/context-matrix/20261014T091908931513Z/summary.json)。5/10精排分数从20真实评分派生，没有独立模型时延；上下文报告仅解释检索指标，不把空回答的自动指标作为生成结果。

**改写**：[6题受控别名](../backend/eval/reports/slice-comparison/20261014T153425634683Z/controlled-original_plus_rewrite.json)经真实保护函数与真实BGE，原问8/9区间、5/6整题，单改写/双分支9/9、6/6，改善CR33。固定SDK输出不是LLM能力测试；额外分支同时增加检索范围，默认仍关闭。

## 3. 引用合法，不代表事实被支持

[有限真实DeepSeek对照](../backend/eval/reports/core-framework-deepseek-bounded-20261014.json)使用5题×2链的冻结词项检索快照，20物理请求=14 strict Agent+5 LC+1 rewrite，生成10答案。模型ID为`deepseek-flash`，有真实usage与提示hash；不是完整BGE/RRF端到端生成。

每链机器状态4 supported/1 not_found。CR07中Agent声称整库没记录，超出当前检索观察；LC补充共享地址空间，但可见引用片段没有支持这个事实。两者都可以通过引用ID检查，仍不满足完整事实支持。[源感知审查](../backend/eval/reports/core-framework-deepseek-review-20261014.json)不是独立人工盲审，人工语义验收pending。

因此把检索、证据进入上下文、格式/引用契约与逐事实支持分层，而不宣布“支持状态=答案正确”。Agent/LC提示与轮次不同，不把usage差异归因为框架本身。唯一真实改写CR02没有变化，其他4题未调用。10/15的发布没有新增生成请求。

10/17另获5次授权，补上[原生BGE检索到真实回答](2026-10-17-native-rag-validation.md)：业务切片写229块，Chroma HTTP与SQL版本/归属核验后直接调用LC业务函数，5次HTTP200，4 supported/1 not_found。主代理逐事实复核，关键解释有可见证据；CR13最后一句明确记录为基本锁模型下的组合推论。实际提示hash逐条对应transport记录，输入10023/输出456 token；查询链路P50为1468ms（n=5，不含285.063s建索引）。同样5道源感知开发题，仍非独立盲测，也不验证默认Agent、全栈HTTP或线上SLA。

## 4. 为什么索引需要持久任务和HTTP进程边界

**故障一**：笔记3块缩成1块，只upsert新块会残留旧尾块。向量准备完再写，成功后清旧ID；异常显式上抛，同输入串行重放收敛。

**故障二**：SQL保存成功，进程退出会丢内存BackgroundTasks。笔记修改与`index_jobs`在同SQL事务登记，worker以generation/lease_token/过期条件CAS领取与完成；旧任务不能确认新版本。代价是最终一致性、有限重试及租约管理；没有分布式事务或续租。

**故障三**：Chroma1.5.9的独立writer修改同目录，长驻PersistentClient `get/count`更新、`query`却旧，删除后仍可能返回已删ID。单writer锁不会刷新读缓存；改用统一HTTP服务，由服务持有索引。

[实际业务探测](evidence/index-http.json)：真SQL+6个独立worker+长驻RAG读者，新增→缩短→再新增→删除→清空均正确，另一owner数据不动，停服务ready503。向量为固定3维，证明存储视图一致性，不证明召回质量。底层HTTP无本项目统一RPC deadline，单机锁不保证跨主机协调。

实现：[index_jobs](../backend/app/services/index_jobs.py)、[worker](../backend/app/services/index_worker.py)、[连接工厂](../backend/app/services/index_store.py)、[故障测试](../backend/tests/test_index_worker_chroma.py)、[完整设计](2026-10-14-chroma-process-boundary.md)。原库migration和旧索引重建未替用户原实例执行。

## 5. RAGFlow 生产后端：把解析/检索/存储委托出去

用户明确最看重在线检索与离线存储，并允许重构。新增 `KB_RETRIEVAL_BACKEND=ragflow` 显式后端：RAGFlow 负责文档解析、切片、向量存储和 hybrid retrieval；SQL 仍是笔记真值，RAGFlow 是可重建派生索引。

| 环节 | 实现 |
|---|---|
| 数据集 | 每用户 `kb_user_{id}`；服务端单 API Key |
| 文档 | 一条笔记一个 `node-{id}.md`；内容变化 delete+re-upload |
| 同步 | 复用 `index_jobs`；worker `--ragflow` 上传、PATCH metadata、触发解析 |
| 解析状态 | `ragflow_documents.state`：parsing/ready/failed/missing；worker 轮询 |
| 检索 | `/api/v1/retrieval` → `document_id` 映射 `node_id` → 当前 SQL fingerprint 复核；chunk 带标题前缀时用 `evidence_verified` 凭据，不靠字面子串 |
| 引用 | 仍由 `finalize_kb_answer` 校验 `[doc:ID]`，不信任 RAGFlow 自带引用 |
| 状态 | `/api/index-jobs/status` 返回 job、dataset、文档状态和失败列表 |
| 对账 | `POST /api/index-jobs/reconcile` 对比 SQL 与 `ragflow_documents`，区分缺失/旧版本/孤儿/失败/手工项；`apply=true` 只登记 index_jobs |
| 回退 | `KB_RETRIEVAL_BACKEND=chroma`；RAGFlow 表保留，不删 SQL 笔记 |

已验证（离线契约 + 真实 HTTP 冒烟）：HTTP 信封与错误、上传/解析/检索请求形状、同步幂等、内容变化替换、失败状态、解析状态轮询、检索映射/fingerprint/跨用户隔离、配置校验、Alembic 迁移、状态/对账 API。

真实冒烟在 WSL Docker 的 RAGFlow v1.0.0（Go API + Infinity）上跑通：health → 建 dataset → 上传 → PATCH metadata → 触发解析 → 轮询 Go `ingestion_status` → 检索 → 清理，`chunks=1`。这次冒烟发现并修复了两个真实兼容性问题：health 响应没有 `data` 信封时客户端误判 unhealthy；Go v1.0 使用 `ingestion_status` 而不是 Python 的 `run`。

**未验证/不能外推**：真实冒烟使用确定性 TEI 兼容测试向量桩（`tei-stub@OpenAI`），不是语义 embedding；因此只证明 RAGFlow 的 I/O 与状态链路，不证明检索质量。真实 TEI/BGE 模型和 36 题 Chroma/RAGFlow 对照仍未跑。

决策、限制和回退见 [ADR 0002](adr/0002-ragflow-backend.md) 与 [接入说明](2026-11-25-ragflow-backend.md)；原始记录见 [ragflow-integration-20261125.json](evidence/ragflow-integration-20261125.json)。

## 6. 检索质量回归：把“找到文档”和“证据进上下文”分开

新增 `eval/run_retrieval_regression.py`，只评检索层，不调用生成模型。指标为
Hit@1/3、MRR、gold evidence coverage、all-evidence rate、nDCG@10 与 p50/p95；
失败桶区分 `not_retrieved`、`node_hit_no_evidence`、`partial_evidence` 和
`all_evidence`。

| 后端 | 用途 | 当前状态 |
|---|---|---|
| `fixture` | 确定性词项检索，CI 门禁/报告 schema | 已跑 36 题；Hit@3=1.0，coverage=0.4074，仅 plumbing |
| `frozen-dense` | 读取已提交的 `k3-dense.json`（真实 BGE、精确内积、20 候选） | 已跑 36 题；Hit@3=1.0，coverage=0.7778，all-evidence=0.7407 |
| `chroma` | 真实 BGE/Chroma 当前索引 | 入口已实现；需要已建索引，未在本轮复跑 |
| `ragflow` | 真实 RAGFlow 检索（RAGFlow 512-token 切片，真实 BGE） | 36 题已跑：keywords=0.7 coverage=0.6481；0.3 coverage=0.8148、Hit@3=1.0；生产默认 0.3 |

fixture 基线在 `eval/fixtures/retrieval-baseline-fixture-20261125.json`；CI 用
`--backend fixture --gate`，不加载模型、不联网。真实 Chroma/RAGFlow 必须各自
生成 before/after，不能拿 fixture 的 Hit@3 冒充真实质量。方法与限制见
[检索质量回归](2026-11-25-retrieval-regression.md)。

真实 RAGFlow 对照（同一 16 篇语料、同一 36 题、同一 512-token 切片，只改
`keywords_similarity_weight`）显示 0.7→0.3 后 Hit@3 0.8519→1.0、
evidence_coverage 0.6481→0.8148、all_evidence 0.5185→0.7407、nDCG 0.8489→0.9541；
MRR 0.9383 略低于 0.7 的 1.0。0.3 已设为 RAGFlow 生产默认，仍可回退；它是
单语料受控实验，不是普遍最优结论。原始报告：
[0.7](evidence/retrieval-regression-ragflow-20261125.json)、
[0.3](evidence/retrieval-regression-ragflow-kw03-20261125.json)。

## 验证与复现

2026-10-15的历史验证：Windows / CPython3.12.15，后端440项、7模块mypy、指定新增模块ruff与前端build。当轮命令输出与首次失败记录见[verification.json](evidence/verification.json)。安装与显式存储/worker步骤见[README_zh](../README_zh.md)。

2026-10-17加入原生回答验收入口的9个离线检查后，该轮完整回归450 passed、5条既有warnings、86.17s；[本轮审计](evidence/native-rag-audit-20261017.json)区分真实请求、离线检查与尚未覆盖项。存储边界修正时的441项记录保留其原时间点。

2026-11-25 P0 回归：默认对话契约改为 LangChain 严格 RAG + `retrieval_mode=current` + rerank/rewrite 关闭；新增默认契约、分层边界、路径卫生测试。`eval.offline_tests --empty-model-cache tests` 为 **468 passed, 43 warnings, 132.01s**；`--verify-isolation` 与 `check_artifact_policy` 均 PASS。本机为 CPython 3.14.0，发布前仍需在约束声明的 3.12.15 环境复跑；原始记录见[baseline-20261125.json](evidence/baseline-20261125.json)。

2026-11-25 RAGFlow 接入后完整离线回归：**514 passed, 43 warnings, 118.70s**；isolation、artifact policy、compileall 均通过；10 个索引/ RAGFlow 模块 mypy 通过，新增模块 ruff 通过。真实 RAGFlow 冒烟与 36 题已用 BGE 跑通；0.3 参数实验已写回，回答生成质量仍未验证。

```text
# backend目录，已有依赖的Python3.12环境
python -X utf8 -m eval.offline_tests --verify-isolation
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
python -m eval.check_artifact_policy
python -X utf8 -m eval.run_slice_comparison --hf-home <已有HF缓存根> --prepare
# frontend目录
npm ci
npm run build
```

当前覆盖本机、临时SQL/Chroma、真实缓存模型实验及有限真实生成；尚未验证生产部署、MySQL并发、长期负载、RPC SLA和独立盲测。测试数与覆盖数只说明这些测试的结果，不能替代上述验证。

公开语料回放辅助类与页面保留为实验候选，当前主API没有挂载`/api/demo/public`，不作为已开通的公开演示入口。当前可运行入口以README的笔记应用和离线实验命令为准。

发布前全回归曾出现439通过/1失败，10/16再次发生。10/16—17已抽离业务代码复现：EphemeralClient在集合缓存压力下保留metadata但向量不可读。实际索引测试现改用生产同款临时HTTP服务，并新增先失败的512集合回归；修正当时441项通过、5条既有warnings，78.51s。没有改业务写入、添加自动重试或宣布第三方内存模式已修复。[复现、负结果及边界](2026-10-17-index-test-storage-boundary.md)。

冻结输入的SHA256按原字节校验。`.gitattributes`保留这16篇公开技术语料、题集及测量报告的字节，避免克隆时LF/CRLF转换使gold/报告hash不符；未改问题、gold或原文语义。
