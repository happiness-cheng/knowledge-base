# 事务索引任务与本地工程验收

第四批修正：真实多进程PersistentClient读写发现query缓存陈旧，已改为生产显式Chroma HTTP服务。本文保留第二批逻辑和历史结果，持续运行方式以[存储进程边界](2026-10-14-chroma-process-boundary.md)为准；本地worker仅允许API停止后的--offline-local模式。

本轮实现已在隔离状态验收；原数据库没有迁移，原向量集合没有重建。暂不处理上线。2026-10-14最后全量：393 passed（空模型缓存、禁外网）；前端构建298模块通过，临时无头Edge登录页渲染通过。

## 实际解决的问题

此前SQL保存成功后，只把索引写入挂在BackgroundTasks上，进程退出后任务丢失；删除异常还会被吞掉。现在节点新增/更新/清空/删除、三种导入和问答保存，把index_jobs登记和笔记修改放在同一SQL事务内。SQL回滚不留任务；请求退出后worker可以从SQL领取。

任务主键(user_id,node_id)，generation递增；SQL条件更新领取15分钟租约，完成必须同时匹配generation、lease_token和未过期租约。异常只记录类型，按2/4/8/16秒退避，最多5次；反复租约超时也进入failed，避免无限重放。worker从当前SQL取正文，读取到不同版本时重新登记，不执行旧任务正文快照。删除没有节点外键依赖。

每个Chroma目录一个writer，跨进程文件锁在打开索引前取得。新块写入指纹，SQL核验所有权、版本及正文片段；Agent/两步RAG/候选检索送模型前再核验。真实内存Chroma测试覆盖upsert成功但响应丢失的重放、新旧SQL交错后收敛和尾块清理。旧集合无指纹时只验证正文片段仍存在，无法证明整篇版本；不自动改写旧集合。

## 接口与操作边界

- `GET /api/health`是存活；`GET /api/ready`实际检查SQL、必要表及Chroma heartbeat，失败503，响应没有连接串/异常详情。它不证明模型、模型缓存或worker处于可用状态。
- 登录用户使用`GET /api/index-jobs/{node_id}`看状态，`POST /api/index-jobs/{node_id}/retry`只重排自己的failed任务；其他用户404，未失败409。
- 应用启动不做DDL。迁移20261014_02只新增index_jobs；已验证临时空库及20260712基线升级保留合成笔记。原库迁移需另行授权；在原库缺表时新写入口会失败，readiness503。
- 未受Alembic管理的旧库，先确认历史/备份，再使用只读`python -m app.schema_validation --baseline-only`核验20260712基线；不能盲目stamp。当前完整表结构用默认核验。这里只提供流程，没有对原库执行。

worker从backend显式启动（路径必须选已授权状态，下面只是接口说明）：

```text
python -m app.services.index_worker --database-url <明确的连接串> --chroma-dir <绝对索引目录> --offline-local
```

此命令仅用于停止API后的本地离线索引；生产API和worker使用同一DATABASE_URL、KB_CHROMA_URL及KB_CHROMA_SUFFIX。HTTP worker还需共用同一主机上的绝对锁目录。无Redis/Celery新增依赖，本轮不启动原状态worker。

## 配置和预算

生产配置不读取个人cc-switch；显式服务配置优先，已有用户加密配置继续使用。默认Anthropic兼容URL是`https://api.deepseek.com/anthropic`，模型ID是`deepseek-flash`。前端说明同步协议；凭据文件不修改。本轮未使用任何在线模型额度。

严格Agent默认完整system/messages/tools输入上限24,000字符，输出max_tokens1,200，最多5次模型调用；SDK隐式重试关闭，超限/循环不额外调用模型收尾。单证据正文6,000字符上限；全文过大返回error，不冒充not_found。字符上限不是DeepSeek tokenizer的精确token硬预算。固定对照评测仍额外用16,000字符、600输出token、3次调用，测试使用MockTransport，未发真实请求。

## 工程取舍与限制

同事务登记解决提交/入队间隙；SQL与Chroma之间仍没有分布式事务，副作用恢复是可重放最终收敛。更新期间暂时没有可用证据是允许状态。租约最长任务超过15分钟时完成会被拒绝并重放，没有自动续租。SQLite路径实测；MySQL虽然沿用SQLAlchemy兼容语句，未对真实MySQL并发/压力验收。不提供公网多实例或服务SLA承诺。

学习[Dify document_indexing_task.py §_document_indexing](https://github.com/langgenius/dify/blob/main/api/tasks/document_indexing_task.py)的持久状态和慢索引解耦，结合本仓库设计事务登记；没有声称Dify就是同一实现。[RAGFlow FAQ §How do I check the status of each RAGFlow component?](https://github.com/infiniflow/ragflow/blob/main/docs/faq.mdx)提供依赖健康区分的参考。直接迁平台会增加部署与存储成本；引入Celery也仍要解决SQL提交到队列之间的间隙。

Docker静态门禁排除凭据/数据库/评测语料报告/权重；Python3.12、Node24与本地验收版本一致，前端目录显式配置，单API worker且不自动DDL。Docker引擎未启动，镜像没有实际构建；GitHub CI定义已写好，未在远端运行。

## 复现命令

从backend运行：

```text
python -m eval.offline_tests --verify-isolation
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
python -m compileall -q app eval
python -m mypy --follow-imports=silent --ignore-missing-imports app/models/index_job.py app/services/index_jobs.py app/services/index_worker.py app/services/evidence_freshness.py
python -m eval.check_artifact_policy
```

类型检查限定新增持久索引4模块，并非全仓库strict；CI lint限定列明的新增运行模块，原全仓库样式债没有批量清理。空缓存测试不等同于真实BGE质量/吞吐测试，检索实验结果仍按此前的真实模型记录解释。5条测试警告为pytest重写及既有SQLAlchemy用法，未扩大改动去清理。
