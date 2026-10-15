# 统一知识库评测入口

入口 `backend/eval/run_benchmark.py` 将文档命中、证据进入上下文、引用合法性、拒答、运行失败分开，并保留逐题观测、分层分母、数据 hash、配置和延迟分位数。实际 Agent 模式复用应用的 `run_agent` 与工具执行，不复制另一条 Agent loop；观察钩子读取完整工具结果，避免只看前 500 字步骤预览。

## 离线复现

在 backend 目录，使用正常安装 requirements 与 pytest 的环境：

```powershell
python -m eval.run_benchmark --output eval/reports/benchmark
python -m pytest tests -q
```

默认 `offline-fixture` 使用内存 Chroma、人工词匹配和固定模型桩，不加载真实 .env / 管理员凭据，不调用模型 API。20 个样例是人工编写的机制 fixture，不是独立盲测。它运行实际 `run_agent` 和 search 工具路径，报告 `model_quality_measured=false`。不能把这里的 100% 写成 RAG 召回率、模型正确率或真实延迟。

本机原 venv 的 Python 3.14 基础路径失效。本次验收另装隔离 Python 3.14.8 并复用原 site-packages，由外部 `offline_knowledge_tests.py` 隔离配置 / Chroma / 外部 socket，允许 localhost 测试通信。原 venv、数据库与索引未修复或重建。这不等于已验证 requirements 在全新环境安装成功。

## 对真实语料评测

用例支持原 v3 七列格式或 BenchmarkCase 对象。`fixtures/legacy_v3_cases.json` 冻结当前 v3 的 55 题（44 正例、11 负例），只含题目和 gold 锚点，没有复制私人笔记。语料快照格式：

```json
{"nodes":[{"node_id":7,"title":"标题","content":"完整原文"}]}
```

必须由使用者显式选择相同用户的完整数据库快照、Chroma 路径和 suffix；入口会检查 node_id/content 是否与该用户数据库一致，集合必须已存在，不会重建索引。

```powershell
python -m eval.run_benchmark --mode retrieval --dataset eval/fixtures/legacy_v3_cases.json --corpus YOUR_SNAPSHOT.json --user-id YOUR_ID --chroma-dir YOUR_CHROMA_PATH --suffix YOUR_SUFFIX --top-k 5
```

本地检索默认 HF offline；没有 embedding 缓存时会失败，不隐式下载。这里只测实际 `retrieve_relevant_nodes`，拒答和引用指标为 null。

```powershell
python -m eval.run_benchmark --mode agent --allow-network --dataset YOUR_CASES.json --corpus YOUR_SNAPSHOT.json --user-id YOUR_ID --chroma-dir YOUR_CHROMA_PATH --suffix YOUR_SUFFIX
```

Agent 模式会使用现有应用配置、发送文本并产生 API 费用，需要确认后执行。`--allow-network` 是显式运行开关，不替代用户的数据授权。工具 top_k 由模型参数决定，报告记录其步骤；CLI top_k 只约束 retrieval 模式。真实 Agent 用例可能调用联网搜索；评测现阶段不能保证请求费用硬上限。本次未执行上述真实语料 / 在线命令。

## 指标解释

- hit@1/@3 和 MRR 以去重文档顺序评分；gold 存在但检索没命中记 0。
- evidence_in_context 要求目标文档返回块中存在完整、有序的 head/tail 锚点；命中文档不代表拿到答案片段。
- gold 文档或锚点已失效单列 invalid_gold，不运行该题；有效题的执行异常计入失败分母，不能冒充拒答成功。
- 引用必须属于当前快照且出现在实际工具上下文；空引用只是合法，不代表答案正确。
- schema v2 保留严格旧指标 `refusal_rate`（显式 marker 且无引用）；另报 `refusal_detected_rate` / `refusal_with_citations_rate`。附背景引用的拒答进入人工复核，既不抬高旧指标，也不直接判为幻觉。这些均为启发式检查。
- 任一题缺失 token 用量，合计为 null；fixture token 是合成值，不是计费记录。
- 延迟包含执行路径；报告区分 offline-fixture / retrieval / agent。分层按 note_type 和 query_source 输出。

历史 28 题的 92.9%、44 题生成报告、11 题拒答报告仍保留为历史实验，不能混为当前生产指标。统一入口是可追溯评测基础设施；后续需独立新增 15–20 个真实问题、固定语料版本、运行真实检索与模型、人工复核失败，再形成简历效果证据。

## 2026-10-12 验收

后端隔离全量测试：143 passed，5 warnings（已有 SQLAlchemy 警告及隔离 harness 的 pytest 插件警告）。前端 `npm run build`：297 modules，通过；前端本轮没有改动。新增评测 8 项测试覆盖证据缺失、无效 gold、执行异常、非法引用、分层分母、纯检索未测指标、重复 ID 和真实 Agent 观察适配。报告默认写独立时间戳文件。

后续受限评测扩展后，后端全量重新验证为 **149 passed / 5 warnings**。增加共享请求限额、缓存用量、失败尝试计数、上下文范围过滤、带引用拒答分项和超限失败分类；限额客户端只用于评测，不改变应用常规客户端。`BoundedAIClient` 配合 SDK `max_retries=0`，每题工具调用与最终回答共享最多 3 次 API 请求，每次最多 1024 输出 tokens。单次响应可包含多个只读工具调用，因此 API 请求数不等于工具次数。

## 授权后的真实模型补充

2026-10-12 用 DeepSeek 官方 `deepseek-flash` 调用实际 run_agent，工具只返回公开人工笔记。两题正例分别正确回答重试上限 / 审批人并给出预期引用；一题负例明确 NOT_FOUND_IN_KB，但附加了实际检索到的背景笔记引用，严格“拒答无引用”条件未通过。该引用合法且没有提供工资值，不能将这项格式 / 契约差异直接等同于幻觉。3 题分别 2 / 2 / 3 次 API 请求，web 等工具禁用；真实 embedding / ANN 检索和私人语料质量仍未评测。

## 后续真实笔记评测（同日，覆盖上述“仍未评测”状态）

在用户单独授权后，使用只读数据库备份与 Chroma 副本完成 20 题真实 bge / ANN 检索及 DeepSeek 官方 Agent 调用。15 正例 / 5 负例为阅读笔记后编写，非独立盲测。仅选定 5 个技术节点进入模型，禁用其他工具，最多 3 请求 / 题及 1024 输出 tokens / 请求。实际 59 请求全部返回：Agent hit@1=14/15、hit@3=15/15、上下文证据15/15、引用 ID 合法20/20、显式拒答5/5，但严格无引用拒答0/5。机械指标不代表整体语义正确率；逐题复核发现推断来源混淆与拒答后的未经核实补充。

环境健康检查发现当前应用 suffix 对应的 user_4_nodes_prod 为空；本轮评测的参考集合 user_4_nodes 有 84 块，不能代表当前部署效果。原 MySQL 启动不稳定，仅在保留备份后的隔离副本读取，未修复原库 / 迁移 / 修改 .env。私有快照、题集和逐题报告保留于仓库外 `agent-career-plan-20261012`，不随项目发布。应用默认 Agent 参数没有切换为本轮受限配置；独立盲测与演示环境恢复仍未完成。
