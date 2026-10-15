# LangChain 严格 RAG 候选：单次生成与授权边界

日期：2026-10-13。本文件记录候选实现与已运行的离线验收，不将离线 fake 的回答当成模型质量实验结果。

## 为什么做这个候选

求职目标需要能解释框架带来的价值，也需要证明调用数、证据权限和失败分类是工程约束。本候选采用固定检索再生成；保留原手写 Agent 作为质量、延迟和复杂性的对照，暂不替换默认路径。

LangChain 官方将 2-step RAG 与 Agentic RAG 分开：前者固定先检索，后者由模型决定检索动作。这里选择前者，是为了验证调用数可控的严格 KB 问答。[官方 Retrieval：§RAG architectures、§2-step RAG、§Agentic RAG](https://docs.langchain.com/oss/python/deepagents/retrieval)

| 方案 | 收益 | 代价与适用边界 |
|---|---|---|
| 本次：LangChain 固定 RAG + 当前 AIClient 的 BaseChatModel 适配器 | 真正使用 Document、BaseRetriever、ChatPromptTemplate、RunnableSequence、ChatModel、parser 和 callbacks；复用认证后的 SDK 客户端；最大一次生成 | 需要维护 SDK 适配器；不自动改写、不自主补查、不处理历史指代；模型无法通过第二次查询弥补首次证据不足 |
| 原手写 Agent | 可决定搜索和继续读取节点，能覆盖需要补查的任务 | 迭代与模型调用更多，权限/预算/错误边界需要在每一轮重复保证；实际收益必须由对照评测证明 |
| 换用完整 LangChain 提供方集成 | 减少自写消息和 usage 适配，沿用标准模型接口 | 需要确保现有用户 Key、base_url、协议、重试配置和真实提供方相容；本次没有为了框架接口重新读取配置或迁移凭据 |

## 实际运行链

```text
当前问题 + 服务端 user_id + 当前 SQL session
  → AuthenticatedKBRetriever（检索一次、SQL 所有权/有效节点过滤）
  → Document 列表与经过过滤的本地观察结果
  → 当前问题/日期/JSON 证据准备
  → ChatPromptTemplate（固定 SystemMessage + 当前 HumanMessage）
  → 字符预算 / 可注入的模型匹配 token 预算
  → BaseChatModel（当前 SDK 单次 messages.create 或离线注入模型）
  → 严格 JSON parser + 输出截断判断
  → finalize_kb_answer（既有回答及引用契约）
```

这是实际 `RunnableSequence`。检索器和模型经过真实 LangChain 生命周期，本地 callback 记录检索结果 ID、生成尝试数和提供方 usage；没有把原 `run_agent` 包装成 lambda 来充当框架接入。

服务接口：

```python
run_langchain_rag(
    db, question, *, user_id,
    ai_client=None, model=None, retrieval=None, observe_tool_result=None,
    top_k=3, current_date=None, history=None,
    max_input_chars=24000, token_counter=None, max_input_tokens=None,
    timeout_seconds=20, max_output_tokens=1200,
)
```

- `user_id` 必须来自已认证的服务端用户；问题、模型和检索行里的 `user_id` 不参与集合或 SQL 所有权选择。
- 自定义 `retrieval` 接口为 `retrieval(question, user_id=..., top_k=...) → list[dict]`；缺省复用当前知识库检索函数。
- `model` 仅接受真实 `BaseChatModel` 实例。离线测试用其子类替换外部模型；生产入口应传已经认证的 `AIClient`。
- 返回既有 `content/source_ids/answer_status/answer_error/steps` 等字段，额外返回 `usage/model_calls/input_budget`，API 是否暴露额外字段由路由和响应契约决定。
- 首版只处理当前问题；非空 `history` 返回 `history_not_supported`，不会偷偷拼接历史或生成改写问题。

## 权限与提示边界

Chroma 用户集合隔离不足以证明索引里的 node_id 仍有效。检索器再次查询当前 SQL：只允许节点存在、属于认证用户且当前正文非空的记录。过滤完成后才创建 Document、调用观察器或进入模型链。正文为空、已删除节点和其他用户记录都不进入模型。

标题与笔记日期取自 SQL 当前节点，不采用索引返回的伪造标题；库内最新日期也只计算当前用户记录。SystemMessage 固定不含文档正文；JSON 证据、标题和日期仅进入 HumanMessage，明确标记为不可信数据。当前日期缺省按 UTC+8 生成，避免将历史笔记数值冒充今日事实。

测试证明恶意正文没有改变消息角色、跨用户内容未送模型和观察器。它们不能证明模型绝对不会被提示注入影响。`finalize_kb_answer` 验证引用属于本轮证据且与 source_ids 一致，不能代替事实语义、证据充分性或时间相关性的评测。

## 单请求、错误与用量

适配器不调用会丢失 usage 的 `AIClient.chat`。它复用 `ai_client.client.with_options(max_retries=0, timeout=...)` 后执行一次 `messages.create`，不声明工具、不做格式修复、不以一般知识兜底。SDK 的默认重试与超时需要显式约束。[Claude Python SDK：§Retries、§Timeouts](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python)

| 情形 | 输出状态 | 生成次数 |
|---|---|---|
| 经过授权过滤后没有非空证据 | 服务端固定 `not_found` | 0 |
| 有证据且回答格式、引用有效 | `supported`；模型也可以判断证据不支持并返回 `not_found` | 1 |
| 检索结果形状非法、检索异常或 SQL 校验失败 | `error/retrieval_error` | 0 |
| 输入预算超限 | `error/input_budget_exceeded` | 0 |
| 提供方超时或失败 | `error/provider_error` | 1 次尝试 |
| 非 JSON、JSON 截断、非法引用 | `error/invalid_answer_contract` | 1 |
| `stop_reason=max_tokens` 或 `finish_reason=length` | `error/output_truncated`，即使局部 JSON 看似合法 | 1 |

`model_calls` 记录 LangChain 模型调用尝试数。现有 SDK 路径没有自动重试，真实 SDK 500 的 MockTransport 测试确认仅发生一次 HTTP 请求。注入模型必须自行符合单次请求约定；本服务不宣称能约束任意子类内部的网络行为。20 秒为 SDK 操作超时，不是覆盖 SQL/检索/网络所有阶段的整条链绝对墙钟期限。

SDK usage 保留普通 `input_tokens`、`output_tokens`、缓存读取和缓存创建字段；仅在缓存字段全部已知时求和为 `total_input_tokens`。LangChain 标准 usage 的输入为总输入时，按其缓存明细单独拆分，避免重复相加。没有实际 usage 时返回 `status=unknown`、计数为 `None`，不把缺失记成零，也不把本地估算写成计费用量。[Claude Python SDK：§Token counting](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python#token-counting)

只配置本地 callback，并用 `tracing_context(enabled=False)` 在链内关闭 LangSmith；即使相关环境变量开启也不启用自动上报。本次未配置外部观察器。[LangSmith：§Trace without setting environment variables](https://docs.langchain.com/langsmith/trace-without-env-vars)

## 输入预算的精确定义

缺省限制是 **24000 个字符**：对实际 System/Human 消息转换成 SDK 的 `system/messages` 结构，再使用 UTF-8 文本的紧凑、非 ASCII 转义 JSON 表示计数。系统提示、当前问题、日期、标题、元数据、正文及 JSON 边界全部计入。预算检查与 SDK 发送共用同一个消息转换函数；真实 SDK 200 的 MockTransport 测试核对了实际请求的消息结构。

这里的字符数是上述序列化文本的 Unicode 字符数，**不是 UTF-8 字节数、不是 token 数，也不是模型上下文窗口保证**。请求中的模型名、输出参数和 HTTP 包装不属于这个输入消息预算。超出预算直接报错，不截断问题或证据后假装正常回答。

需要 token 预算时必须同时传 `token_counter(messages)` 与正整数 `max_input_tokens`。计数器接收最终的真实 System/Human 消息。只有计数器覆盖该候选模型/提供方实际分词和消息包装时，才能称为该候选的 token 硬预算；任意近似 tokenizer 不能当成通用保证。缺省不运行在线 count_tokens，也不增加额外请求。

## RED / GREEN 与实际测试

命令工作目录为仓库 `backend`，使用新建干净 Python 3.12 环境和仓库内隔离入口。入口阻止个人配置及外部网络读取，SQL/Chroma 使用测试存储；模型和检索提供方由离线实例替换。此次 LangChain Core 为 1.6.10，Anthropic SDK 为 1.13.0。

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\生产工程实施-20261013\env-clean\Scripts\python.exe' -X utf8 -m eval.offline_tests tests/test_langchain_rag.py -q --tb=short
```

实际 TDD 过程：

1. 最小公开接口未实现：`2 failed, 1 warning in 3.75s`；核心真实链实现后：`2 passed, 1 warning in 0.51s`。
2. 补齐权限、错误、预算、SDK 和截断验收：`15 failed, 21 passed, 1 warning in 4.16s`。其中真实 SDK 测试还确认 `httpx.Client` 与 SDK 1.13.0 不兼容，需使用已安装的 `httpx2.Client`；测试据此改正，未添加依赖。
3. 对应生产逻辑实现后：`36 passed, 1 warning in 3.59s`。
4. 增加真实 SDK 200 的请求预算核对、缓存总数语义、环境开启追踪时的关闭检查及非法计数器边界：`42 passed, 1 warning in 2.28s`。

真实 SDK HTTP 测试使用内存 MockTransport 和明确的测试占位值，没有读取或调用真实 Key/提供方。SDK 1.x 的 HTTP 客户端兼容要求也与官方文档一致。[Claude Python SDK：§Configuring the HTTP client](https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python#configuring-the-http-client)

warning 为隔离入口先导入应用后的 `anyio` 断言改写提醒。语法编译 `python -m py_compile app/services/langchain_rag.py tests/test_langchain_rag.py` 退出码为 0。新增三文件的实际文本空白检查输出 `whitespace_issues=[]`、退出码 0；Git 的 no-index 检查没有报告空白错误，退出码 1 表示新增文件与空文件存在差异。没有用这些测试报告 Recall、答案准确率、P95 或成本改善。

## 下一步验收与剩余限制

- 路由集成、固定数据集的检索配置与原手写 Agent 对照，由后续接线及评测完成；本文件记录的 GREEN 是服务实现验收，不表示 API/前端整链路全部验收。
- 当前不会主动补查或改写含糊问题，也不读取多轮历史。要引入这些功能，需要独立比较质量收益、额外调用和错误传播。
- SQL 存在与所有权校验不等于向量内容的新鲜度证明；索引可能返回属于当前节点的旧内容，需结合索引版本/对账进一步解决。
- 切片、标题和证据仍可能超过模型分词后的窗口；默认字符限制不能代替提供方匹配的 token 计数器。
- 当前本地步骤与 usage 不构成持久监控、请求分布式追踪、告警或完整审计。

面试可展示的已验证点是：框架链具体组成、授权先于模型与观察器、SDK 默认重试的治理、字符/token 预算的不同含义、错误与“无证据”的区分。质量是否优于手写 Agent 必须等真实对照结果，不能由框架名称或离线 fake 推出。

激活已安装项目依赖的 Python 环境后，在仓库 `backend` 目录可复制执行：

```powershell
python -X utf8 -m eval.offline_tests tests/test_langchain_rag.py -q --tb=short
```
