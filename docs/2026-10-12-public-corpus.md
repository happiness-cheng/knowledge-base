# 公开技术导读演示库：本地检索阶段

## 范围与结论

按用户选择建立独立公开语料索引。原 MySQL、原 `.env`、原向量索引和既有演示数据库未修改。这一阶段没有模型 API 请求，也没有数据库 schema 变更。

当前语料是五篇官方资料的短中文编辑导读，明确标记 `editorial_summary`，不是官方全文副本。保留官方 URL、章节、页面版本或核对日期，以及导读内容 SHA256。没有保存原始 HTML，也没有实现或验证完整网页正文解析。因此目前不能宣称长文档解析、海量知识库效果或生产级文档接入。

| 主题 | 官方来源与章节 |
|---|---|
| 分布式计算 | [AWS](https://aws.amazon.com/what-is/distributed-computing/)，What Is Distributed Computing?、advantages、use cases |
| CUDA | [NVIDIA](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/cuda-platform.html)，§1.3、§1.3.2 |
| Python yield | [Python 3.14](https://docs.python.org/3.14/reference/expressions.html#yield-expressions)，§6.2.10、§6.2.10.1；页面标题 3.14.8 |
| PyTorch autograd | [PyTorch](https://docs.pytorch.org/tutorials/beginner/basics/autogradqs_tutorial.html)，Tensors, Functions and Computational graph、Computing Gradients、Disabling Gradient Tracking；页面标题 2.14.0+cu130 |
| Kubernetes | [Kubernetes](https://kubernetes.io/docs/concepts/overview/)，Overview、Why you need Kubernetes and what it can do、What Kubernetes is not |

未固定版本的来源记录为 2026-10-12 核对，不能伪称永久版本链接。PyTorch 资料只支持自动求导和推理梯度记录的入门解释，不能覆盖“整个框架原理”。语料按五个已知问题选择，所以不是独立盲测。

## 实现

复用项目 `split_by_headings`，沿用 BGE-large-zh-v1.5、查询指令、归一化向量、L2 距离和每节点最多两块。独立脚本复制了检索分组逻辑，未调用完整生产 `rag_service`，避免其模块初始化接触原数据库和索引；不能据此宣称完整应用 Agent 已接入新库。

`eval/public_corpus.py` 负责来源必填项、官方 URL 白名单、唯一正整数 ID、导读类型、内容哈希、标题/章节/正文完整输入预算和禁止覆盖目录。运行脚本在仓库外使用新目录；离线开关和 socket 拦截禁止模型下载与遥测。

可复现实验材料在 `C:\Users\陈独秀\agent-career-plan-20261012`：

- `public-corpus.json`：五篇导读与来源。
- `build_public_corpus.py`：离线索引和八题本地检索。
- `compare_public_context.py`：冻结排序，仅改变每文档片段数。
- `verify_public_answers.py`：默认 dry-run，显式授权开关才调用官方模型；冻结检索重放，非应用工具循环。
- `public-corpus-20261012T150859598522Z`：独立 Chroma、输入快照、manifest、cases、逐题片段、评测报告、片段数对照。

本地运行命令：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' 'C:\Users\陈独秀\agent-career-plan-20261012\build_public_corpus.py'
```

每次创建新目录，禁止覆盖已有运行。当前脚本依赖本机缓存及外部 Python，尚未包装成可移植的仓库内 CLI。

## 实测与关键取舍

独立库 5 篇、10 块、1024 维。实际模型运行时最大长度 512 tokens；标题+章节+正文+特殊 token 的最大输入为 131。manifest 记录模型缓存 revision、配置与 tokenizer 哈希、语料/切片/脚本哈希；没有记录模型权重文件哈希。

用户五题保留原文字及 `pyyhon`、`pytroch` 拼写，没有 query rewrite。五题均首位命中对应文档，同块锚点覆盖 5/5；0 无效题、0 执行错误。新增内容使原本缺资料的主题可检索，不能算作算法提升。总库只有五篇，这种高命中率不支持泛化准确率结论。

冻结向量排序、问题和语料，只改每文档返回块数：

| 每文档最多块数 | 正例锚点进入上下文 | 漏证据题 | 八题平均正文字符数 |
|---|---|---|---|
| 1 | 4/5 | U04 PyTorch | 280.125 |
| 2 | 5/5 | 无 | 562.0 |

PyTorch 的首位片段是推理说明，自动求导核心段在第二块。两块保住证据，代价是这组样例上下文正文字符数约翻倍。字符数不是模型输入 token 或实际费用；没有验证回答准确率变化。结论：继续沿用现有两块配置，暂不增至三块或引入精排；小型、定向整理语料不足以支持长期参数最优判断。

三个模拟缺证据问题也能返回近似片段。K8s RTO 题首位距离约 0.770，Python 正例约 1.117；此批样例不能用单一单调距离阈值完美区分可答与不可答。向量相近不代表有项目实测。拒答率与引用正确率保留 null，必须在线回答后再检查；这里没有伪造拒答结果。

## 验证与剩余工作

- 新增模块先跑 unittest，缺实现时失败；实现后 6 项通过。
- 离线完整后端 pytest：180 passed、5 条既有警告，75.63 秒。
- 新模块、测试和三个外部脚本 Ruff 通过；编译检查和 Git diff 空白检查通过。
- 首次 Ruff 发现两处赋值 lambda，改为 def 后通过。上下文重放脚本首次误读报告字段 `rows`，核对既有契约为 `cases` 后修正，原命令已重跑成功。
- 严格回答脚本 dry-run：8 题、每题最多 1 请求、每请求最多 1024 输出 tokens；没有读 Key、没有联网。

主代理按需求、边界、安全、规范、可回退性自审，没有调用或伪造独立 reviewer。新索引目录创建与既有目录拒绝覆盖有测试；没有删除旧数据。未改前端，本阶段没有重复前端构建或浏览器检查；没有配置类型检查任务。

下一步需新的明确 API 范围授权：仅发送本批公开导读检索片段，检查五个概念问题及三个缺证据问题的结构化状态、引用和事实。即便通过，也只是冻结检索的回答协议验证，不是完整应用工具循环或真实用户线上效果。尚未将新库挂载到 8766 页面。

## 获授权后的八题官方模型验证

用户另行明确允许这轮最多8次公开资料请求后，执行如下命令；没有自动重试，也没有重跑在线批次：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' 'C:\Users\陈独秀\agent-career-plan-20261012\verify_public_answers.py' --run-dir 'C:\Users\陈独秀\agent-career-plan-20261012\public-corpus-20261012T150859598522Z' --allow-public-model-eval
```

实际使用已有 DeepSeek 官方凭据、`deepseek-flash`，Anthropic兼容接口；Key仅用于请求认证，没有放进问题或上下文，没有修改。SDK `max_retries=0`，每题请求上限1，输出上限1024。原始报告目录：`public-answers-20261012T151910287985Z`。

| 检查项 | 结果 |
|---|---|
| 实际请求数 | 8/8，每题1次 |
| 请求错误 / 输出契约错误 / 截断 | 0 / 0 / 0；全部 stop_reason=end_turn |
| 五个概念题的结构化状态 | 5 supported |
| 五题引用 ID 集合检查 | 5/5，均为本题实际检索文档 |
| 三个缺证据题 | 3 not_found，原始JSON均 answer为空、source_ids为空 |
| 缺证据题背景引用与泛化建议 | 0 |
| 输入 tokens（含缓存读） / 输出 tokens | 7645 / 1725；单题最大输出611 |

以上为账本和格式检查结果，**不是八题全部语义正确**。逐题对照导读人工复核：U02–U05的主要事实直接有支持；U04主动限定只解释autograd和推理，未将其冒充PyTorch全部原理。U01新增“分布式系统的核心是分布式计算”的概括，导读没有直接支持这层等同表达，需要收紧；其余定义、计算用途、扩展与容错限制有支持。此外这篇导读缺少岗位常见的分布式服务、状态一致性等内容，不能假装已覆盖面试深度。

三个负例没有编造项目RTO、本机驱动/吞吐、密钥值。RTO缺失已在导读中显式说明，所以该负例较容易；Key从未被提供给模型，因此不能将拒答称为经过验证的真实密钥泄漏防护。没有同模型同语料的旧规则在线基线，不能把本轮3/3拒答与此前不同语料的负例直接算提升百分比。

离线复核命令：`D:\python.exe audit_public_answers.py`（脚本在外部材料目录）。实际退出0，检查八次账本、输出上限、stop_reason、契约及引用集合；结果保存为`verification.json`，包含原始报告和执行器哈希、逐题人工意见。两个相关脚本Ruff通过。本轮没有生产代码修改，因此没有重复完整后端和前端测试。

后续主线：先将公开库检索、严格回答与证据展示接入可演示的应用流程，并增加不同表述及更难的缺证据样例；当前小型导读集不支持优先上精排。U01的表述问题已记录，尚未通过提示词或模型再次调用验证修复。八次授权额度已耗尽。原库与8766服务保持原状，新库尚未挂载到页面。

## 页面接入（后续完成，覆盖上节“尚未挂载”状态）

地址：[公开资料演示](http://127.0.0.1:8766/public-demo)。同源登录沿用隔离演示的 `demo / demo-local-only`；笔记库主页在隔离服务启用公开材料时显示入口。服务重启更换临时会话密钥，已有浏览器可能需要重新登录。

页面明确区分两种操作：

1. 选择固定问题：读取此前八次真实模型调用的答案记录与当时的检索片段；标记“真实模型回答回放 · 本次未调用模型”。引用按钮滚动到相应资料；U01显示人工复核意见。
2. 自由输入问题：调用真实本地BGE和独立Chroma库，按文档保留最多两块、返回前三篇；只显示当前片段，标记“实时本地检索 · 未生成回答”。不替换成近似固定问题答案，不调用外部模型。

这是已完成的真实答案回放与本地检索流程，**不是新的在线模型生成，也不是完整Agent工具循环**。来源区可查看五篇编辑导读全文、官方链接、章节和版本/日期。没有新增SQL表、导入到原笔记表或改动.env。

实现：`eval/public_demo.py`读取冻结语料与答案、校验片段哈希和引用范围，拒绝其他问题的记录及非公开证据。外部隔离服务在索引工厂替换前独立打开公开库，校验存量片段与冻结内容一致、实际模型报告hash一致；所有公开数据API仍要求登录，原写入/外发限制保持。

主代理自审覆盖：答案不能套到自由问题、公开索引与原索引分离、没有原库/密钥进入响应、无删除/schema/.env操作、React文本转义和外链noopener、空问题/未知case/未登录响应、移动布局与滚动。没有调用或伪造独立reviewer。

验证记录：

- 新接口模块先因缺实现RED，初始4项GREEN；补充问题错配/引用越界/非快照证据后7项全部通过。
- 最终完整后端回归：`offline_knowledge_tests.py --site-packages C:\Users\陈独秀\knowledge-base\backend\venv\Lib\site-packages tests -q --tb=short`，使用外部Python3.14且cwd为backend；187 passed、5条既有warnings，34.12秒。执行器隔离配置与索引并阻断外网。
- `npm.cmd run build`：298模块，2.45秒初次/1.66秒滚动修复后；最终JS383.93kB、gzip121.02kB。
- `isolated_knowledge_demo.py --verify`：20笔记与快照一致，84块原检索top1=19，原索引hash未变，写入403、模型503。
- `verify_public_demo_browser.py`：真实8766生产构建页面，5正例回放、3无引用拒答、引用跳转、来源展开、自由yield/return检索首位Python、主页入口、移动端检查通过；401/404/422/403符合预期，pageerror=0、外部浏览器请求=0、模型请求=0。
- 首次浏览器检索断言使用Playwright默认5秒，模型冷加载期间超时；日志确认请求仍在正常加载，显式扩展断言等待后通过。另补滚轮回归复现了原body overflow:hidden导致公开页不能滚动的问题，新增独立height:100vh/overflow-y:auto容器后原回归通过。
- 新增模块/测试/外部服务/浏览器脚本Ruff通过，compileall与git diff --check通过（仅既有Windows换行提示）。前端没有现成独立lint/type任务，本轮未新增工具链。

浏览器证据保存在外部 `reports/public-demo-browser/verification.json` 与桌面/移动截图。测试只在独立headless浏览器中登录，没有修改用户浏览器存储。服务继续以loopback隐藏进程运行。

剩余限制：外部固定目录与本机缓存依赖仍未整理成可移植仓库内CLI；实时模型回答关闭；原MySQL尚未修复；语料只有五篇短导读且不是盲测；U01表述仍待验证修复。下一阶段优先整理可复现启动和演示材料，真实模型工具循环或新API批次需独立额度授权。
