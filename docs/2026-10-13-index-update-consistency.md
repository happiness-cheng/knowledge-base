# 笔记更新后的索引一致性：第一实施切片

日期：2026-10-13。

## 问题与验收标准

`add_node_to_index` 原来只对当前切片执行 upsert。三块正文缩成一块时，`7:0` 被覆盖，`7:1` 和 `7:2` 仍可被检索；正文清空时函数直接返回，三块旧内容全部保留。SQL 中保存了新正文，不代表向量索引已同步。

本切片通过服务公共写入入口和真实 Chroma 内存集合验证以下行为：

- 在没有同一节点并发写入的前提下，成功返回后仅保留当前正文的切片；空正文或没有切片时清理该节点。
- 同步更新正文、标题、切片元数据和向量；保留同用户的其他笔记及其他用户集合。
- 兼容旧版单 ID `str(node_id)`，包括没有 `node_id` 元数据的旧记录。
- 嵌入失败时不写入或清理原索引；存储操作失败向调用者抛出异常。
- 同一内容串行重放后收敛，不产生重复 ID；不能将此称为事务或多 worker 并发保证。

## 根因定位

探测前的假设和可观察预测如下：

| 假设 | 预测 | 结果 |
|---|---|---|
| 更新只有 upsert，没有删除旧 ID 的差集 | 缩短正文后，新首块正确但旧尾块仍在 | 真实 Chroma 测试确认 |
| 空正文直接 return | 清空正文后原有 ID 和正文全部保留 | 真实 Chroma 测试确认 |
| 集合选择或过滤导致跨节点污染 | 其他节点或其他用户的记录也会改变 | 本切片正常路径测试中未出现；仍作为回归边界 |

`node_id:chunk_index` 是稳定 ID。upsert 会更新这次提交的 ID，并不意味着“替换整篇笔记的所有切片”。测试直接读取真实集合中的 ID、文档、元数据和向量，避免把总数量或模拟函数调用当成一致性证据。

## 候选方案与取舍

| 方案 | 行为和收益 | 代价与失败边界 |
|---|---|---|
| 本次采用：全量生成新向量 → upsert 当前 ID → 清理旧 ID 差集 | 保留当前 ID/检索契约；无需新增依赖或改 schema；嵌入失败保留旧索引；同输入重放可修复中途失败 | upsert 和清理之间存在新旧内容混合窗口；稳定 ID 会覆盖旧首块；需要两次 ID 查询和可能的一次 delete；并发不同版本可能相互覆盖或删除 |
| 后续候选：版本化切片 → 切换活动版本 → 回收旧版本 | 在设计好活动版本存储与读取规则后，可以先完整写入候选版本，再让检索只读取选定版本 | 必须修改写入与检索契约，并设计可靠版本选择、并发条件更新与垃圾回收；SQL 与 Chroma 仍不是天然的跨存储事务；增加存储和恢复成本 |

没有采用“先删整篇，再计算向量”：向量计算或写入失败会让之前可用的笔记彻底失去索引。当前阶段先完成可回放的最小修复；只有读一致性、并发写或可用性要求明确需要时，再实施版本化方案。

## 实现顺序与故障矩阵

全部切片的向量先在内存中准备完成，然后一次 upsert。写入成功后在当前用户集合内查找本节点的 metadata ID，以及旧版单 ID，删除不属于当前 ID 集合的记录。没有切片时跳过 upsert，直接执行同一清理流程。服务不捕获这些异常。

| 故障位置 | 可能留下的索引状态 | 已验证的恢复方式 |
|---|---|---|
| 第二块嵌入生成失败 | 全部旧切片与旧向量保持原样 | 同输入重放后写入新块并清理旧尾块 |
| upsert 执行前失败 | 旧索引保持原样 | 同输入重放 |
| upsert 已完成但调用报错 | 新首块与旧尾块混合 | 同输入重放并清理差集 |
| 清理所需的 ID 查询失败 | 新首块与旧尾块混合 | 同输入重放 |
| delete 执行前失败 | 新首块与旧尾块混合 | 同输入重放 |
| delete 已完成但调用报错 | 索引可能已经正确，调用仍报错 | 同输入重放后成功返回 |
| 空正文 delete 失败 | 执行前报错保留旧块；执行后报错可能已清空 | 同一空正文重放后为空 |

故障测试只包装真实集合的一个失效操作，其余操作仍执行真实 Chroma。它们验证调用前/调用后异常的恢复，不证明真实远程存储、进程崩溃、磁盘损坏或部分提交的所有行为。

## RED / GREEN 验证证据

隔离入口 `offline_knowledge_tests.py` 将原数据库配置切到内存 SQLite，将持久 Chroma 客户端替换为内存客户端，并禁用外部网络。测试使用唯一集合名、固定切片和确定性四维嵌入，不调用 tokenizer、联网模型或真实业务索引。此次实际使用 Chroma 1.5.9。

原建议的 `D:\python.exe` 入口未能运行测试：该解释器为 Python 3.13.5，项目的 orjson 扩展为 `orjson.cp314-win_amd64.pyd`，导入时报 `ModuleNotFoundError: No module named 'orjson.orjson'`。原虚拟环境解释器路径也已失效。本次使用已有 Python 3.14.8 解释器读取原 site-packages；没有修改虚拟环境、安装依赖或读取凭据。

实际执行命令（PowerShell）：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' 'C:\Users\陈独秀\agent-career-plan-20261012\offline_knowledge_tests.py' --site-packages 'C:\Users\陈独秀\knowledge-base\backend\venv\Lib\site-packages' tests/test_rag_index_updates.py -q --tb=short
```

修复前，两个测试均因目标问题失败：

```text
test_shortening_three_chunks_to_one_removes_old_tail
AssertionError: {'7:0', '7:1', '7:2'} != {'7:0'}
test_empty_content_removes_all_previously_indexed_chunks
AssertionError: 原有三条记录仍在，预期为空
2 failed, 1 warning in 0.90s
```

最小修复后原两例通过；补齐正常更新、隔离、兼容及故障重放后：

```text
19 passed, 1 warning in 1.29s
```

随后用同一入口同时运行 `tests/test_rag_index_updates.py tests/test_index_audit.py -q --tb=short`，得到 `23 passed, 1 warning in 1.23s`，原有只读对账测试未退化。

warning 为隔离入口先导入应用后 pytest 报告的 `anyio` 已导入、不能断言改写，未出现测试失败。

语法编译命令：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' -m py_compile 'C:\Users\陈独秀\knowledge-base\backend\app\services\rag_service.py' 'C:\Users\陈独秀\knowledge-base\backend\tests\test_rag_index_updates.py'
git diff --check -- backend/app/services/rag_service.py backend/tests/test_rag_index_updates.py docs/2026-10-13-index-update-consistency.md
```

二者退出码均为 0。原 site-packages 未安装 mypy、pyright、ruff、flake8，项目未发现其配置，此次类型和 lint 检查标记为跳过；未为该修复添加工具依赖。人工检查确认本次改动不新增密钥、网络访问、动态执行或跨用户清理，业务改动只在 `add_node_to_index`。

## 剩余限制与面试表述边界

- 本切片没有修复已经存在于真实集合中的旧块，只修复后续调用的更新逻辑；真实索引对账和经授权的修复需另行实施。
- 同一节点同时更新 A/B 时，稳定切片 ID 会相互覆盖，清理也可能删除另一版本的尾块。没有加入仅进程内的锁来声称多 worker 安全；后续需要可靠版本控制或跨 worker 的写入协调。
- SQL 保存与后台索引写入仍是两条链路。`nodes._safe_add_to_index` 会记录带 traceback 的 warning，但不把失败改成 API 的同步失败；本次没有新增持久重试、任务状态、告警或自动对账。服务异常可见不等于用户已经看见同步失败。
- `remove_node_from_index` 的异常处理未在本次修改范围内。不能用本切片声称删除链路已获得相同的错误传播保障。
- 当前“清空”指 `content == ""`；空白字符串和只含标题的输入仍遵循原切片规则，未新增正文语义判定。
- 本次没有运行在线 RAG 质量评测，没有测吞吐/延迟，也没有以此宣称完整生产就绪。后续必须验证最终组合及真实业务入口。

可以讲清的已验证结果是：发现更新仅 upsert 导致的旧尾块残留，用真实存储做 RED/GREEN，采用生成向量后写入再清理的最小方案，覆盖了故障后重放；同时明确接受短暂混合窗口及并发版本限制。不能声称已经实现事务更新、自动恢复或生产数据修复。
