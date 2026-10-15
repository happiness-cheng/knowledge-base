# Chroma进程边界：真实故障与服务端修正

2026-10-14第四批：440项离线回归通过，新增索引连接模块纳入类型/lint检查。原数据库、原索引及凭据未改；临时Chroma服务已停止，没有部署。

## 本项目中实际发生的问题

单writer锁能够拒绝同目录第二个worker，却不能让另一个长驻PersistentClient读进程刷新向量缓存。真实Chroma1.5.9两进程试验中，writer更新/缩短后get/count正确，query仍保留旧ID/旧距离；新增节点无法向量召回，删除后count0仍query已删ID/null。SQL指纹可以过滤陈旧证据，不能把召回缺失补回来。

因此，第二批“独立worker+共享本地目录”的方式不能作为持续读写拓扑使用；历史EphemeralClient测试只证明重放/清理逻辑，不证明跨进程向量可见性。

## 修正方案与取舍

使用官方HttpClient，让一个Chroma服务进程拥有索引，API和独立SQL索引worker连接同一显式KB_CHROMA_URL。保留SQL事务任务、generation/租约、fingerprint及现有集合命名，不换向量库、不引入Redis/Celery。

增加一个服务和HTTP往返成本，换取读写使用同一向量索引视图；相比把writer搬进API，能够继续解耦慢索引与请求。没有用重启reader或清理内部缓存作为生产修复。依据：[官方Python Client §PersistentClient / HttpClient](https://docs.trychroma.com/reference/python/client)、[官方issue #3792](https://github.com/chroma-core/chroma/issues/3792)。

统一工厂拒绝URL中的用户信息、query/fragment、额外路径及非法端口，错误不回显原地址。production必须配置合法HTTP(S)地址；HTTP不可用时失败，不回退到本地索引或创建备用目录。已运行服务的Chroma依赖断开，readiness返回503；启动时无法建立连接则启动失败。

## 接口

KB_CHROMA_URL通过显式环境或Settings配置，API与worker必须相同；本次没有修改.env。生产worker示意（数据库和锁路径由操作方选定，不是本次部署命令）：

```text
python -m app.services.index_worker --database-url <明确SQL连接串> --chroma-url <与API相同HTTP(S)origin> --lock-dir <本机所有worker共用的绝对锁目录>
```

HTTP模式不接受--chroma-dir或--offline-local；--lock-dir只保存本机锁文件，不是索引数据。全部worker必须同主机同锁路径；它不是跨主机锁。API/worker的KB_CHROMA_SUFFIX、数据库、用户collection命名仍需一致。

本地PersistentClient保留开发/离线用途；先停止API，再运行：

```text
python -m app.services.index_worker --database-url <明确SQL连接串> --chroma-dir <绝对目录> --offline-local
```

旧命令缺少--offline-local会在打开SQL/索引前拒绝；production本地模式仍拒绝。该标志是操作方对停止API的明确声明，没有新增跨进程API存活探测器。禁止把它用于长驻本地reader并发更新。

## 实际结果与限制

本机短生命周期Chroma服务、合成SQLite、固定3维向量：6次独立worker CLI处理真实SQL任务，长驻真实rag_service.retrieve_relevant_nodes验证新增、缩短更新、再新增与两个删除步骤；新向量距离2→0，尾块消失，新ID可查询，删除后为空；其他owner集合保持1块。全任务succeeded。停止服务后真实ready函数SQL=ok/index=unavailable，503。应用链路12.531s，不是模型质量/线上吞吐测量。

离线测试固定KB_CHROMA_URL为空，两个独立评测入口也清除此服务选择；本地诊断显式目录优先。两个项目的离线网络守卫在真正HTTP transport逐跳检查目标，阻断本机代理/重定向绕过，清除代理环境，同时允许内存MockTransport契约。本轮一次负向隔离探测在修复前经本机代理产生1次合成identity GET/502，没有笔记、凭据或模型请求；后续验证仅使用不转发的本机假代理。

原库index_jobs迁移、旧索引更新仍未执行；新服务没有导入原数据。没有远端CI、部署/TLS/服务鉴权或跨主机单writer验收。Chroma1.5.9 HTTP实现使用无默认请求timeout的httpx客户端；本次没有通过私有字段强行修改，未声明Chroma RPC硬期限或整个Agent墙钟期限。KB strict调用次数/输入/输出上限和工具容量仍生效，但不等于端到端SLA。

## 验证

```text
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
# 440 passed，5条既有warnings，73.14s
python -m mypy --follow-imports=silent --ignore-missing-imports app/models/index_job.py app/services/index_jobs.py app/services/index_worker.py app/services/evidence_freshness.py app/services/embedding_input.py app/services/tool_executor.py app/services/index_store.py
# 7模块通过（不是全仓strict）
python -m compileall -q app eval
python -m eval.check_artifact_policy
```

新增factory/入口/production配置以及同步、异步直接/重定向代理守卫都有失败到通过证据。原有警告未扩散清理；真实模型召回/回答实验仍依此前记录解释。
