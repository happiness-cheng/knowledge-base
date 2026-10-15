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

因此把检索、证据进入上下文、格式/引用契约与逐事实支持分层，而不宣布“支持状态=答案正确”。Agent/LC提示与轮次不同，不把usage差异归因为框架本身。唯一真实改写CR02没有变化，其他4题未调用。此轮发布未新增生成请求。

## 4. 为什么索引需要持久任务和HTTP进程边界

**故障一**：笔记3块缩成1块，只upsert新块会残留旧尾块。向量准备完再写，成功后清旧ID；异常显式上抛，同输入串行重放收敛。

**故障二**：SQL保存成功，进程退出会丢内存BackgroundTasks。笔记修改与`index_jobs`在同SQL事务登记，worker以generation/lease_token/过期条件CAS领取与完成；旧任务不能确认新版本。代价是最终一致性、有限重试及租约管理；没有分布式事务或续租。

**故障三**：Chroma1.5.9的独立writer修改同目录，长驻PersistentClient `get/count`更新、`query`却旧，删除后仍可能返回已删ID。单writer锁不会刷新读缓存；改用统一HTTP服务，由服务持有索引。

[实际业务探测](evidence/index-http.json)：真SQL+6个独立worker+长驻RAG读者，新增→缩短→再新增→删除→清空均正确，另一owner数据不动，停服务ready503。向量为固定3维，证明存储视图一致性，不证明召回质量。底层HTTP无本项目统一RPC deadline，单机锁不保证跨主机协调。

实现：[index_jobs](../backend/app/services/index_jobs.py)、[worker](../backend/app/services/index_worker.py)、[连接工厂](../backend/app/services/index_store.py)、[故障测试](../backend/tests/test_index_worker_chroma.py)、[完整设计](2026-10-14-chroma-process-boundary.md)。原库migration和旧索引重建未替用户原实例执行。

## 验证与复现

2026-10-15在Windows / CPython3.12.15按仓库CI同范围验证：后端440项、7模块mypy、指定新增模块ruff与前端build。当前命令输出与首次失败记录见[verification.json](evidence/verification.json)。安装与显式存储/worker步骤见[README_zh](../README_zh.md)。

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

发布前首次全回归曾出现439通过/1失败：Chroma1.5.9在`test_replacing_a_node_preserves_other_nodes_and_users[新首段]`的`get(include=embeddings)`抛出内部`Error finding id`。未改业务代码，针对该文件8次重复共152项通过，再次完整440项通过。尚未稳定复现或定位根因，保留为间歇性存储测试风险，不称为已修复；没有加入自动重试来隐藏失败。

冻结输入的SHA256按原字节校验。`.gitattributes`保留这16篇公开技术语料、题集及测量报告的字节，避免克隆时LF/CRLF转换使gold/报告hash不符；未改问题、gold或原文语义。
