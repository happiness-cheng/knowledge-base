# 严格知识库回答契约

本切片解决受限对照中“模型已经承认缺证据，却仍贴背景引用、继续给建议”的输出收口问题。原规则和追加prompt的两道负例严格无引用拒答均为0/2，因此没有直接采用该追加prompt。

方案选择：增加显式严格KB模式，以结构化状态和服务端校验处理可机械判断的边界。只靠追加prompt不能保证边界；事后简单删引用仍会留下无证据建议。此次不新增模型裁判、不更换检索框架、不做数据库迁移。

## 接口与兼容性

聊天请求新增 `kb_only`，默认false，旧普通Agent、联网和通用知识模式继续使用现有路径。需要严格笔记回答时显式发送：

```json
{"content":"笔记中有没有 Redis 跨地域 RPO 实测值？", "kb_only":true}
```

发送到现有 `POST /api/chat/conversations/{conversation_id}/messages`，使用已有登录凭据。`kb_only=true` 和 `ai_search=true` 冲突，返回422，且不写入用户消息。请求通用知识或联网补充时使用原模式，不能同时要求严格KB证据。

前端已新增“回答范围”：严格知识库（页面默认）、自动扩展（原Agent）、通用AI（ai_search）。后端kb_only默认false保持其他调用兼容。缺证据/错误分别显示且不能保存到知识库，历史显示状态未记录；显示时去掉机器拒答标记前缀。已有只读演示服务仍禁用模型调用，不能宣称实时模型链路已验收。

严格模式仅开放 search_knowledge_base / get_node_details，服务端也拒绝模型擅自提出的其他工具。详情只能访问本轮检索取得的节点。语义索引结果在进入模型和评测观察器前，按数据库当前用户所有权重新过滤；不存在、其他用户及空正文不能加入证据集合。

## 回答契约

严格模式最终模型输出必须为无代码围栏的JSON：

```json
{"status":"supported", "answer":"笔记记录了多路复用 [doc:19]", "source_ids":[19]}
```

| 状态 | 服务端处理 |
|---|---|
| supported | 要求非空正文、非空正整数引用列表；正文引用集合须与source_ids完全一致，且属于本轮当前用户证据集合；通过后返回正文 |
| not_found | 忽略模型的建议、背景引用和数字；固定返回 `NOT_FOUND_IN_KB: 本次检索未找到支持该问题的证据。`，source_ids为空 |
| error | 模型/工具/数据库校验失败、未先检索、格式错误或引用越界；返回固定错误说明、空引用，不声称无资料，不回退通用回答 |

即时响应新增 `answer_status: supported | not_found | error`；原模式为null。最终步骤展示与返回正文一致。执行错误依然是现有聊天API中的业务结果（HTTP200加answer_status=error），模式参数冲突才是HTTP422。

未修改Message表，未持久化新状态，历史GET返回answer_status=null。不能通过sources为空推测旧回答究竟是not_found还是error。若未来需要状态历史、分析面板或产品默认切换，需另做设计；数据库迁移应单独获得授权。

## 验证与边界

离线测试通过真实run_agent入口，并含实际聊天路由→Agent→收口的用例；只替换外部模型和检索提供方，非真实DeepSeek评测。覆盖固定拒答、合法正例、未检索/越权引用、格式及类型错误、模型/工具/数据库失败、外部工具阻止、非法工具参数、通用模式兼容、参数冲突、历史读取与最大迭代最终回答。

先观察新增严格入口测试11失败（缺kb_only参数），实现后通过；API接点2失败后修复；边界自审补测非法参数和数据库异常2失败后修复。没有新增模型API调用，也没有采用上轮未通过的prompt候选。

运行验证命令（使用仓库外已准备的Python和隔离依赖入口）：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' 'C:\Users\陈独秀\agent-career-plan-20261012\offline_knowledge_tests.py' --site-packages 'C:\Users\陈独秀\knowledge-base\backend\venv\Lib\site-packages' tests -q --tb=short
D:\python.exe -m ruff check app/services/kb_answer_contract.py app/services/agent_service.py app/routers/chat.py tests/test_kb_answer_contract.py
D:\python.exe -m compileall -q app/services/kb_answer_contract.py app/services/agent_service.py app/routers/chat.py tests/test_kb_answer_contract.py
git diff --check
```

最重要的限制：程序仅验证状态、格式、用户权限和引用集合。模型可能把本来缺证据的问题标成supported，也可能引用合法节点却说了原文没有的内容；这些仍需逐句语义评测。not_found表示这次检索没有支持材料，不能证明整个知识库完全没有。结构化协议是否稳定被DeepSeek遵守尚未在线验证；如果模型输出普通文字则fail closed为error，不称质量成功。

本轮实际结果：全量174 passed / 5 warnings（anyio重写提示与已有SQLAlchemy警告）；上述4个Python文件Ruff通过、compileall退出0、git diff --check退出0（只有Git换行提示）。未找到KB项目mypy/pyright配置，未运行静态类型检查；前端未改动，未重复构建。限定4文件的硬编码凭据及eval/exec检索无匹配；已人工检查权限、调用边界与新旧diff，没有Git提交、.env修改、原库/索引操作或模型调用。审查由主代理自审，未使用子代理。

后续页面验收：npm run build，297 modules；Playwright实际页面三模式切换、payload、缺证据/失败无保存按钮、引用及历史状态通过，pageerror0。请求由公开人造API fixture应答，无模型调用；dev与现有8766静态构建均通过，真实隔离服务登录/20笔记/HTTP2详情复测通过。前端无独立type/lint配置，未运行额外检查器；仅修改聊天组件和API客户端，未引入依赖、修改凭据或数据库。

下一步冻结独立用户问题，先本地诊断切片/候选召回，再申请有明确范围的真实模型验证；新评测应同时观察格式失败、误拒答、无依据supported及端到端状态，不能只报固定拒答分支的通过率。
