# 有限框架对照：准备完成，真实生成效果待确认

入口是 `backend/eval/run_core_rag_comparison.py`。默认仅 dry-run，纯标准库读取已冻结的技术语料和模拟题，不导入应用、不加载个人配置、不访问网络。离线测试已经走真实 Agent 循环、LangChain Runnable 和 Anthropic SDK，只在 HTTP transport 替换响应；模拟回答不能计为真实模型质量。

## 准备好的外发范围

当前必须通过`--credentials-file`显式指定用户给定的DeepSeek文件，只读取DEEPSEEK_API_KEY，不修改文件、不选择cc-switch。使用`deepseek-flash`（DeepSeek-V4.1-Flash）及官方兼容端点`https://api.deepseek.com/anthropic`，非思考模式。官方依据：[首次调用API §参数表](https://api-docs.deepseek.com/zh-cn/)与[使用Anthropic API §通过Anthropic API调用DeepSeek模型 / §简单字段](https://api-docs.deepseek.com/zh-cn/guides/anthropic_api/)。指南整页读取曾超时，搜索返回的官方章节已成功取得，真实调用也验证了协议。

发送五道development模拟题CR02 / CR07 / CR13 / CR19 / CR26，以及冻结16篇技术笔记的选定文本。快照按词项重叠排序固定，每题两个文档、每文档最多两段、每段最多800字符。Agent的get_node_details先执行原SQL鉴权，再限定为与另一框架相同的冻结片段；完整HTTP JSON每次硬限制16,000字符。没有读取真实笔记数据库。

请求上限为 25 个实际 HTTP 请求：每题 strict Agent 最多 3 次、LangChain 最多 1 次，可选 rewrite 最多 1 次。回答最多 600 输出 token，rewrite 最多 300。SDK clone 设置 retries=0；HTTP transport 在发送前检查、计数，包括失败响应。HTTP 错误或预算越界停止后续批次。没有在线 judge、格式修复或自动扩大额度。凭据/header 不写入报告；模型、提示 hash、延迟、普通/缓存 usage 分项保留，usage 缺项报告 unknown。

CLI 的 `--allow-network` 与 `--new-request-budget` 是操作闸门，不代替用户授权。配置读取仅发生在闸门通过之后；应用首次导入使用临时 home、内存 SQLite 和 Ephemeral Chroma，原数据库/索引不变。

## 能证明什么

离线验收：五题 × 两条真实框架链，模拟 SDK 响应产生 15 个 HTTP transport 调用、10 条结果，包含 supported 与 not_found；原 SDK retries 配置保持不变。无配置的纯 dry-run 可从任意 cwd 执行。预算越界在 transport 委托前拒绝。

后续在线只能作为小规模框架可用性、契约、成本与失败模式观察。两方案的 prompt、工具 schema 和节点详情流程不同；固定的词项快照也不是已测 BGE/RRF 检索链。不能把差异归因于“框架本身”，不能把五题称为独立盲测或最终正确率。最终答案逐条人工核对事实与证据，当前 `human_fact_review=pending`。rewrite 候选保存后，还需独立做检索收益对照。

## 命令

在 backend 目录，用独立 Python 3.12 环境运行：

```powershell
python -m eval.run_core_rag_comparison --dry-run --output eval/reports/core-framework-plan-20261014.json
python -m eval.offline_tests tests/test_core_rag_comparison.py -q --tb=short
```

收到具体外发及新额度授权后才可运行：

```powershell
python -m eval.run_core_rag_comparison --allow-network --new-request-budget 25 --credentials-file C:/Users/陈独秀/agent-career-plan-20261012/.env.deepseek-smoke --prepare-rewrites --output eval/reports/core-framework-online-new.json
```

输出必须是现有目录中的新文件；默认不覆盖既有证据。

## 早期误选来源记录（已停止使用）

用户明确授权上述外发范围并确认新额度后，已执行一次25请求上限的批次。实际当前cc-switch配置是`api.b.ai`与`Qwen3.8-Flash`，沿用该配置。首个请求返回HTTP错误即停止，实际发送1次。随后仅为补齐状态码记录，剩余额度设24再诊断一次；返回HTTP404后停止，发送1次。合计2次，不是两个25次批次。

报告：`backend/eval/reports/core-framework-online-20261014.json`及`core-framework-online-diagnostic-20261014.json`。没有真实可用答案、rewrite或usage，不能据此报告正确率、成本或模型拒答率。记录中provider_error与not_found明确分开。

本地SDK源码确认请求路径应为`/v1/messages`；B.AI官方[API Reference §Messages API / §Error Responses → HTTP Status Codes](https://docs.b.ai/llmservice/api/)也列此路径，并解释404可能是资源或模型不存在。尚不能确定本次404的具体原因；不得说成额度不足或擅自换模型/修改凭据。下一步应确认该账户可用的准确model ID与Messages端点。官方文档不能代替当前账户的成功调用证据。

之后只读模型列表探测1次超时，累计3次。用户纠正：已给独立DeepSeek文件，B.AI/Qwen已不用且无额度。停止该来源，移除默认回退并记录全局纠错；本任务不再诊断旧网关。CLI没有显式凭据文件即拒绝，不再推断默认提供方。

## 最终DeepSeek真实结果

第一轮DeepSeek发出2次请求均HTTP200，随后整篇节点详情使完整JSON超过16,000字符；第三次发送前拦截，没有外发。失败测试复现后，限定本次对照详情为同一份冻结片段，以剩余20请求预算续跑完成。没有改原笔记、gold或生产Agent默认。每题Agent两轮工具机会后，必要时第三次收尾；先完成两个框架，再用剩余预算生成rewrite。

`core-framework-deepseek-bounded-20261014.json`记录20次HTTP200，10条框架结果，0执行错误：每个框架4条supported、1条not_found。授权范围内累计实际请求25次=旧来源3+DeepSeek超预算前2+最终20。保留原失败报告，不把诊断调用排除后声称只消耗20次。

| 最终批次 | 实际请求 | 普通输入token | 缓存读取token | 总输入token | 输出token |
|---|---:|---:|---:|---:|---:|
| strict Agent，5题 | 14 | 15,908 | 8,832 | 24,740 | 1,728 |
| LangChain，5题 | 5 | 3,785 | 0 | 3,785 | 339 |
| rewrite，1题 | 1 | 198 | 0 | 198 | 29 |

总输入28,723、输出2,096；普通/缓存没有重复计数。这是服务器实际usage，不是账单。出现了真实缓存读取，但官方兼容章节说明cache_control被忽略，不能归因为客户端显式prompt cache。框架的工具、提示与调用轮次不同，不能将token差异单独归因于LangChain框架。

唯一rewrite为CR02，模型返回原问，unchanged_rewrite回退；另4题未调用，不报告改写质量收益。

主代理逐条按实际冻结上下文复核：CR02/CR13/CR19核心内容有片段支持，CR26两框架均拒答且无引用。CR07关键gold段未进入上下文，Agent只给部分切换信息且过度声称整库没有相关记录；LangChain补充“共享同一地址空间”等未获引用片段支持的解释。因此不公布整体语义正确率，更不是100%。独立人工验收仍pending；这是源感知的主代理审查，未调用在线judge。记录见`core-framework-deepseek-review-20261014.json`。

框架可用，证据选择和事实支持性仍需完善。本轮是有限开发样例、固定词项快照对照，未验收生产BGE/RRF端到端生成、全部36题或独立盲测。
