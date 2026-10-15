# K2：有界查询改写候选

新增 `backend/app/services/query_rewrite.py`，提供默认关闭的独立候选。它保留原问，最多生成一条改写分支；失败就返回原问，没有重试、格式修复或隐式降级模型调用。2026-10-14 完成本节离线验证。

## 1. 接口与接入方式

```python
rewrite_query(
    question,
    enabled=False,
    model=None,              # 调用者注入的 BaseChatModel
    ai_client=None,          # 或调用者已有的 SDK 客户端包装
    history=(),
    bindings=None,
    preserve_terms=(),
    max_input_chars=12000,
    max_rewrite_chars=1000,
    max_history_turns=2,
    timeout_seconds=10,
    max_output_tokens=300,
)
```

`model` 与 `ai_client` 只能选择一个。模块不构造 `AIClient` 或 Anthropic 客户端，不读取 `.env`、全局模型/密钥配置，也不连接数据库。现有 LC SDK adapter 可以由调用者创建后注入；候选没有直接导入 `langchain_rag`，因为其模型实体导入会间接加载应用配置。

返回字段：

| 字段 | 含义 |
|---|---|
| `original_query` | 原始问题，始终保留 |
| `rewrite_query` | 接受的改写；拒绝或关闭时为 None |
| `queries` | `[original]` 或 `[original, accepted_rewrite]`，最多两条 |
| `accepted` | 是否接受改写分支 |
| `model_calls` | 本次调用候选模型/SDK 的尝试数，0 或 1 |
| `usage` | 提供方报告的用量；未知项为 None，不猜测成零 |
| `failure_reason` | disabled、校验、预算、provider、格式或约束错误 |
| `input_budget` | 字符预算及实际 system/messages 序列化字符数 |
| `trace` | 本地调用次数与接受/拒绝记录，不包含异常原文 |

调用者可将 `queries` 分别用于检索，再通过统一候选融合比较原问与双分支。LC 的显式接线见第 6 节；默认仍关闭，不替接入方做召回实验结论。

## 2. 单调用与预算

默认 `enabled=False`，返回原问和 `disabled`，模型调用为 0。启用后先验证配置、历史和完整 prompt 字符数，再调用一次模型。输入字符计算覆盖 system 和承载问题/绑定/受保护词的 user JSON；它不是 token 计数，也不宣称覆盖 HTTP 头或 SDK framing。输出改写另受 1,000 字符限制。

SDK 路径只执行：调用方现有 client 的 `with_options(max_retries=0, timeout=...)`，随后一次 `messages.create`，带 `max_tokens` 输出限制。原 client 的重试配置保持不变。测试使用真实 Anthropic SDK 与本地 MockTransport，验证 503 和 timeout 都只有 1 个请求；没有网络模型调用。

BaseChatModel 路径只执行一次 `invoke`，并传入输出限制与 timeout。通用注入模型是否遵守这些参数、是否自行缓存或重试，属于该模型适配器的约定；不能仅凭本函数一次 invoke 就声称任意适配器只有一次网络请求。现有已关闭 SDK 重试的 adapter 可作为注入对象使用。

坏 JSON、重复 key、额外字段、空文本、截断标记、超预算、timeout 或 provider 错误均降回原问。协议仅接受 `{"rewrite": "文本"}`。Thinking/tool 块不当作最终正文，不添加第二次“修复 JSON”请求。异常文本不进入返回 trace，避免把提供方内部信息混入实验报告。

## 3. API、数字与用户限制

改写须保留：当前问题里的 ASCII 标识符、所有数字出现次数、包含否定/仅限/必须/最多等限制词的原始子句、显式 `preserve_terms`，以及显式历史绑定的目标。

API 与数字按完整词面检查：`get_user` 不能以 `get_users` 冒充，10 不能以 100 冒充。历史绑定目标也经过同样检查。拼写纠正或别名可以增加检索词，但不能删掉受保护原名，例如 `ANN` 可以扩为 `ANN approximate nearest neighbor`。

这是保守的词面验收，**不是语义等价证明**：英文普通词也可能被视作标识符；含“不”的普通子句可能被过度保护。合法的改写因此可能被拒绝。模型也可能保留这些词面却改变关系或增加错误意图，需要真实任务集进一步判断。默认保留原问和失败关闭，是当前有界候选的取舍；不能写成“已解决所有改写语义漂移”。

## 4. 多轮指代与恶意历史

历史只接受调用者显式提供的有限 `user` 消息，默认最多 2 轮，格式为 `{"role":"user","content":"..."}`。提供历史必须同时给出绑定，例如：

```python
history = [{"role": "user", "content": "解释 HTTP2"}]
bindings = {"它": "HTTP2"}
```

绑定别名必须出现在当前问题，绑定目标必须出现在这些 user 内容中；目标还须出现在接受的改写中。模块不自动猜指代，不接受 assistant answer 作为历史证据。提供方的 system 说明与 user 数据使用独立消息角色；历史中的 `SYSTEM:...` 等字符串留在 user JSON，不提升为指令。

接入方仍需根据认证用户和当前会话挑选历史；该纯候选模块没有数据库鉴权能力。结构分区与词面检查不能证明真实模型抵抗所有恶意历史：本轮测试验证的是攻击文本留在数据角色、错误绑定被拒绝和 assistant 历史不进入模型。

调用在 `tracing_context(enabled=False)` 中进行，不配置 LangSmith，不自动外发 trace。trace 由返回值留给本地调用者使用。测试确认离线模型观察到 tracing disabled。

## 5. 验证与可讲范围

在独立 managed Python 3.12 环境执行：

```powershell
# cwd: knowledge-base/backend
& 'C:\Users\陈独秀\agent-career-plan-20261012\生产工程实施-20261013\env-clean\Scripts\python.exe' -X utf8 -m eval.offline_tests tests/test_query_rewrite.py -q --tb=short
# 23 passed, 1 warning
```

warning 为测试入口预加载 anyio 导致的 `PytestAssertRewriteWarning`，没有测试失败。TDD 首次因模块缺失失败，最小拼写/关闭路径达到 2 passed；新增约束、历史、截断、usage 和 SDK 测试时为 13 failed / 6 passed。另两个回归先复现 API 前缀误判与 JSON 重复 key，修复后全部通过。

另执行新文件 `py_compile` 和 `ruff check`，均通过；独立导入确认 `app.config`、全局 `app.services.claude_client` 未被加载。没有安装新依赖、调用在线模型、读取个人配置或修改既有业务入口。

本轮只能说明“查询改写候选可运行，有关闭、单调用、预算、协议和保守约束验收”。拼写、别名和指代输出来自离线固定 fixture，**没有证明真实 LLM 的召回净收益、答案收益、延迟或实际 token 成本**。是否采用需由原问 baseline 与同数据/预算的候选检索实验决定，且分开报告改写失败、额外成本和约束丢失。

## 6. LangChain 实际接线：仍须显式启用

`run_langchain_rag` 新增 `rewrite_enabled=False`、`rewrite_model=None`、`rewrite_history=()`、`rewrite_bindings=None`、`preserve_terms=()`。启用时复用 `rewrite_query`，有注入 rewrite_model 则调用该模型，否则使用服务器已选择的 ai_client SDK。改写字符上限共享该次 `max_input_chars`；输出最多 `min(300, max_output_tokens)`。没有接受改写时，仍只检索原问。

一次 LangChain Retriever 生命周期内部最多执行两个分支，**原问分支实际调用**，再调用接受的改写分支。每个分支先通过 SQL 验证认证用户、文档存在与非空正文，再创建 Document 与通知 observer；不能依靠检索返回的 owner/title 绕过服务器校验。observer 按分支保留原问与改写的实际观察。

双分支以 `(node_id, SHA-256(content))` 稳定去重，同一分支同一内容只计一次排名贡献；使用 `k=60` 的 RRF 合并排名，忽略来源 raw score。按合并排名选 `top_k` 个父文档，每父最多保留 2 个完整 Document，不裁正文。默认单分支保留已有返回行为。`evidence_selection` trace 记录候选与选择块数、所选 node_id/content hash、分支数和选择限制。

最终生成始终使用**原始问题**，不把检索改写替代用户问题。完整 system/messages/evidence 经过原有字符与条件 token 预算；超限时不生成，也不会偷偷截断正文。预算拒绝会记录 `input_budget_rejected`，已经发生的改写调用仍计入总调用数。

结果中的 `model_calls = rewrite_model_calls + generation_model_calls`；`rewrite_usage` 和 `generation_usage` 分开。原有 `usage` 字段继续等于 generation usage，是兼容别名，不能再与 `generation_usage` 相加。另返回 `rewrite_trace`、`rewrite_queries`、`rewrite_accepted` 与 `rewrite_input_budget`，便于区分关闭、拒绝改写、检索和生成预算问题。改写失败没有隐式修复请求，检索分支异常按原有 retrieval_error 失败，不自动伪装完整召回。

这条候选同时改变了**查询分支、候选范围、RRF 合并和完整块选择规则**。不能把它与原问检索的差异称为纯模型改写的单变量收益；专用对照应固定分支/候选/最终选择预算，再分开分析语义改写与额外检索的作用。

新接线测试先因缺少 rewrite 参数得到 5 failed；实现后与既有 LC 测试联跑为 47 passed。测试使用真实 Runnable/ChatModel 生命周期与离线 BaseChatModel，覆盖默认关闭兼容、双分支原问观察、共享用户过滤、去重/RRF、完整块上限、改写失败、原问生成与超限时“改写 1 次、生成 0 次”。另外补测同一认证 ai_client 分别执行单次改写和生成、模型/usage 分开。三组最终联跑为 **71 passed，1 个 anyio 预加载 warning**；ruff 与 py_compile 通过。

```powershell
# cwd: knowledge-base/backend
python -X utf8 -m eval.offline_tests tests/test_langchain_rewrite_pipeline.py tests/test_langchain_rag.py tests/test_query_rewrite.py -q --tb=short
```
