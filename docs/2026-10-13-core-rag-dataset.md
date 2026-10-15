# 第一批核心 RAG 冻结题集与语料

冻结日期：2026-10-13。本轮只验证数据契约，为下一步 dense / BM25 / fusion 对照提供输入；没有执行检索质量比较、在线模型调用或答案质量评分。

题集为 36 题，27 正例 / 9 负例；语料 manifest 引用 16 篇仓库内原技术笔记，累计 211437 字节。原文件没有修改或复制到 fixture。相近主题之间保留自然干扰，网络层笔记是无正例 gold 的额外干扰文档。

## 题目来源与划分

全部题目都标记 query_source=agent_simulated，由生成者阅读原文后编写。本批没有取得那 5 个历史问题的可验证逐字文本，因此没有把主题摘要冒充 userprovided 问题。development=17 题，heldout=19 题；以 template_group 整组划分，同组不会横跨两侧。heldout 表示检索对照的预留组，不是独立盲测，也不反映真实用户问题频率。

| 类别 | 正例 | 负例 | 总题数 |
|---|---:|---:|---:|
| 具体 API / 错误 | 5 | 1 | 6 |
| 语义改写 | 6 | 0 | 6 |
| 多文档综合 | 6 | 0 | 6 |
| 易混淆概念 | 6 | 0 | 6 |
| 缺证据 | 0 | 6 | 6 |
| 拼写 / 指代 | 4 | 2 | 6 |

缺证据负例涉及缺失的 Socket 错误修复、CUDA、Python yield、PyTorch、K8s、项目真实配置/指标，以及没有前文的指代。它们明确标记 missing_coverage 或 ambiguous_query，未编造正例或修复步骤。typo_pronoun 层包含自带有效上下文的口语指代及拼写错误，也包含无上下文指代负例；两者不能合并成已验证的多轮能力。

## 冻结文件与读取

- 题集：backend/eval/fixtures/core-rag-20261013.json
- 语料 manifest：backend/eval/fixtures/core-rag-corpus-20261013.json
- 纯加载与校验：backend/eval/core_corpus.py

SHA256（原始文件字节）：

- manifest：`8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b`
- dataset：`c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a`

题集 metadata 记录 manifest hash；case_metadata 记录 topic、template_group、split、query_category 和每个 gold 的原文区间。cases 内只使用已有 BenchmarkCase 字段，因此 benchmark.load_cases 仍可读取。所有 gold 使用 gold_evidence，语义为全部必需；具体计分口径见 2026-10-13-multi-evidence-benchmark.md。

在 backend 目录本地读取：

```python
from pathlib import Path
from eval.core_corpus import load_manifest_corpus, validate_core_dataset

manifest = Path('eval/fixtures/core-rag-corpus-20261013.json')
dataset = Path('eval/fixtures/core-rag-20261013.json')
corpus = load_manifest_corpus(manifest, Path('..'))
cases = validate_core_dataset(dataset, corpus)
```

该模块只导入标准库和纯 benchmark 契约，不导入 app、embedding、Chroma 或数据库；只有调用时才显式读取指定文件。加载器拒绝改动后的 source hash、缺文件、重复 ID/路径、绝对路径、..、非 Markdown 文件和外部语料目录之外的路径；解析后的路径仍需留在仓库内。gold 文档与有序 head/tail 必须在对应原文存在；模板跨 split、用例元数据缺失、负例缺覆盖状态同样拒绝。

## 语料来源

| node_id | 原文件 | SHA256 |
|---:|---|---|
| 1001 | 计算机操作系统 - 进程管理.md | `81bd8a81bb1055b6663bbf4e853a50cba4b34c802ca393da9feb66f455f89300` |
| 1002 | 计算机操作系统 - 死锁.md | `87a42f25f08e4a301a4ce8a7519089606fc77f6cd352cb544b6dabd9e96537a0` |
| 1003 | 计算机操作系统 - 内存管理.md | `8f9bd33ec0604c1a913cfbc098dd63566cc7780752d9c3961fc7aae8490b7a32` |
| 1004 | 计算机网络 - 传输层.md | `e5825d7e4dd94556ce040970057ebfe7a63adaad2d6ec6b6022696ebb608452c` |
| 1005 | 计算机网络 - 应用层.md | `0bf0a7d12f9590d3bb07c6fe3df16f9cf29609a9146217ccb9f4012c4df4826e` |
| 1006 | 计算机网络 - 网络层.md | `5e54865e07cbe176c144a711e0e22894ab19de6a48d0cbb0b6d215b42fe641f2` |
| 1007 | SQL优化.md | `a7ba76f04513e5dcd548915ad356caef806568e66a7fd25c5fddc3d9c845cdf5` |
| 1008 | Redis.md | `23faa226b377bbb997daf22af95302d0ff2842d9a0f4f0167f37d261ed984001` |
| 1009 | MySQL.md | `9bb762abdaa7bec4cec9f81b070ee3c7166696d43e53ea7b76f967a46cf7b981` |
| 1010 | 数据库系统原理.md | `34aa3bf502064d0c53d6a130891f2d20609d17771fb62eadb00f946b9282b1d8` |
| 1011 | Socket.md | `02dbf18d6b038e17f3eef0483003e222ff0c063575d01942013dd551771b49a3` |
| 1012 | Docker.md | `d34637bf2dd4a477d8c4a3bbe060922a14f13e255836863f0e0c17642b01951a` |
| 1013 | 分布式.md | `7c523c492d44d141e3df4f95225a19f99de338943ffabf5907ee99fb358dacd0` |
| 1014 | 缓存.md | `f311fc2ba7b04d638398992f177cd8380d7d148df94ed79b9f24dec9a65a0572` |
| 1015 | 消息队列.md | `28b0238e43ff193a5bb2dd73a65d5180897dcf6c166a2fdb18e42a23a01341e1` |
| 1016 | 系统设计基础.md | `c474e2f11587641ab8d1c9cc5bb841e1dbf5e986de403c016563e55937c767b2` |

源文件均位于 backend/eval/corpus/external/。选入前仅检查疑似私钥、常见 provider key、凭据赋值、邮箱身份与 Git 身份配置，16 篇未命中这些模式；此模式扫描不等于完整秘密审计。Git多用户配置.md 按身份内容用途直接排除且未读取。manifest 记录检查范围与排除原因，不记录任何疑似值。

本轮仅本地读取仓库内技术语料，没有读取 .env、凭据或真实数据库，没有下载原文链接或图片，也没有向模型/API 外发。后续在线对照需要先确认实际发送的文件/区间、问题、供应商与成本范围；本轮 local_only 标记不能代替外发授权。

## 逐题 gold 范围

行号来自 manifest 冻结的原始文本，以换行计数。每个列出的区间都是必需证据；准确的 head/tail 在题集 JSON 中。负例没有 gold，必须按覆盖缺失或歧义解释。

| case | 类别 | split | gold 文档 | 原文范围 / 覆盖状态 |
|---|---|---|---|---|
| CR01 | 具体 API / 错误 | heldout | 1007 | SQL优化.md §2.2 前导模糊查询 L28–L39 |
| CR02 | 具体 API / 错误 | development | 1013 | 分布式.md §一、分布式锁 / Redis 的 SETNX 指令 L55–L57 |
| CR03 | 具体 API / 错误 | development | 1008 | Redis.md §二、数据类型 / LIST L90–L105；Redis.md §二、数据类型 / LIST 输出 L105–L110 |
| CR04 | 具体 API / 错误 | development | 1011 | Socket.md §二、I/O 复用 / select L110–L112 |
| CR05 | 具体 API / 错误 | heldout | 1007 | SQL优化.md §2.3 在属性上进行计算 L42–L51 |
| CR06 | 具体 API / 错误 | heldout | 无 | missing_coverage |
| CR07 | 语义改写 | development | 1001 | 计算机操作系统 - 进程管理.md §进程与线程 / 区别 / 系统开销 L65–L65 |
| CR08 | 语义改写 | heldout | 1003 | 计算机操作系统 - 内存管理.md §虚拟内存 L25–L25 |
| CR09 | 语义改写 | heldout | 1004 | 计算机网络 - 传输层.md §TCP 的三次握手 / 三次握手的原因 L68–L70 |
| CR10 | 语义改写 | development | 1012 | Docker.md §一、解决的问题 L17–L17 |
| CR11 | 语义改写 | heldout | 1010 | 数据库系统原理.md §四、隔离级别 / 提交读 L237–L239 |
| CR12 | 语义改写 | development | 1015 | 消息队列.md §二、使用场景 / 异步处理 L43–L43；消息队列.md §二、使用场景 / 业务条件 L47–L47 |
| CR13 | 多文档综合 | development | 1013, 1008 | 分布式.md §一、分布式锁 / Redis 的 SETNX 指令 L59–L59；Redis.md §六、键的过期时间 L402–L402 |
| CR14 | 多文档综合 | heldout | 1002, 1010 | 计算机操作系统 - 死锁.md §必要条件 L27–L30；数据库系统原理.md §三、封锁 / 读写锁 L145–L146 |
| CR15 | 多文档综合 | development | 1003, 1014 | 计算机操作系统 - 内存管理.md §页面置换算法 / 最近最久未使用 L69–L71；缓存.md §一、缓存特征 / 淘汰策略 L33–L35 |
| CR16 | 多文档综合 | heldout | 1005, 1004 | 计算机网络 - 应用层.md §域名系统 L29–L32；计算机网络 - 传输层.md §TCP 的三次握手 / 三次握手的原因 L68–L68 |
| CR17 | 多文档综合 | heldout | 1009, 1007 | MySQL.md §一、索引 / B+ Tree 与红黑树的比较 L57–L67；SQL优化.md §2.2 前导模糊查询 L28–L39 |
| CR18 | 多文档综合 | development | 1011, 1016 | Socket.md §一、I/O 模型 / I/O 复用 L67–L67；系统设计基础.md §一、性能 / 性能指标 L38–L38 |
| CR19 | 易混淆概念 | development | 1001 | 计算机操作系统 - 进程管理.md §进程与线程 / 进程 L35–L35；计算机操作系统 - 进程管理.md §进程与线程 / 线程 L45–L45 |
| CR20 | 易混淆概念 | development | 1004 | 计算机网络 - 传输层.md §TCP 流量控制 L126–L126；计算机网络 - 传输层.md §TCP 拥塞控制 L132–L132 |
| CR21 | 易混淆概念 | heldout | 1010 | 数据库系统原理.md §二、并发一致性问题 / 不可重复读 L109–L109；数据库系统原理.md §二、并发一致性问题 / 幻影读 L115–L115 |
| CR22 | 易混淆概念 | heldout | 1008 | Redis.md §八、持久化 / RDB L433–L437；Redis.md §八、持久化 / AOF L443–L443 |
| CR23 | 易混淆概念 | development | 1014 | 缓存.md §四、缓存问题 / 缓存穿透 L89–L89；缓存.md §四、缓存问题 / 缓存雪崩 L98–L98 |
| CR24 | 易混淆概念 | development | 1012 | Docker.md §五、镜像与容器 L73–L75；Docker.md §五、镜像与容器 / 可写层 L77–L77 |
| CR25 | 缺证据 | heldout | 无 | missing_coverage |
| CR26 | 缺证据 | development | 无 | missing_coverage |
| CR27 | 缺证据 | heldout | 无 | missing_coverage |
| CR28 | 缺证据 | heldout | 无 | missing_coverage |
| CR29 | 缺证据 | development | 无 | missing_coverage |
| CR30 | 缺证据 | heldout | 无 | missing_coverage |
| CR31 | 拼写 / 指代 | heldout | 1008 | Redis.md §八、持久化 / AOF 同步选项 L450–L450 |
| CR32 | 拼写 / 指代 | heldout | 1004 | 计算机网络 - 传输层.md §TCP 的四次挥手 / TIME_WAIT L96–L96 |
| CR33 | 拼写 / 指代 | development | 1014 | 缓存.md §一、缓存特征 / 淘汰策略 L33–L33 |
| CR34 | 拼写 / 指代 | development | 1012 | Docker.md §五、镜像与容器 / 只读层 L75–L75；Docker.md §五、镜像与容器 / 可写层 L77–L77 |
| CR35 | 拼写 / 指代 | heldout | 无 | ambiguous_query |
| CR36 | 拼写 / 指代 | heldout | 无 | missing_coverage |

## 本次验证及限制

Python 3.12.15 全新隔离环境，在 backend 目录执行：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\生产工程实施-20261013\env-clean\Scripts\python.exe' -X utf8 -m eval.offline_tests tests/test_core_corpus.py tests/test_benchmark.py -q --tb=short
& 'C:\Users\陈独秀\agent-career-plan-20261012\生产工程实施-20261013\env-clean\Scripts\python.exe' -X utf8 -m ruff check eval/core_corpus.py tests/test_core_corpus.py
```

TDD 第一轮 14 failed（缺纯加载模块）→14 passed；冻结 fixture 验收 1 failed / 14 passed（文件未存在）→联合回归 41 passed / 1 warning。Ruff 首次发现 import 排序与测试字符串连接格式 4 项，修正后 All checks passed。warning 为隔离入口预导入 anyio 引起的 pytest rewrite 提示。纯 import 子进程确认 app/chromadb 未加载。

原文是教学笔记，包含旧版本信息和简化表述；本次验证锚点存在，不验证技术事实的新旧或正确性。多文档题是为机制覆盖主动构造的综合问题，不能据此推断真实使用难度。原文包含目录、图片链接和参考资料，这些重复文本也会影响检索；本轮未预先清洗以刷分。题数仅 36，不支持稳定的总体质量估计。任何效果结论都需下一轮固定输入、候选配置与逐题输出后再判断。
