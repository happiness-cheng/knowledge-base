# 完整输入预算、证据版本与有界工具执行

本批继续修补已批准生产化范围，未迁移原库、重建原索引或调用在线模型。2026-10-14最终隔离全回归413项通过，类型检查限定新增6模块；此前实验和验收记录仍作为历史证据。

## 完整embedding输入

真实缓存BGE tokenizer复现：正文480token，但80字标题加小节后完整输入565token，超512窗口。原来只算正文并预留固定标题预算，编码会丢失尾部表示。

现在先实际计算完整title/heading/body/特殊token，再重切正文；极长标题仅缩短用于embedding的前缀，metadata保留完整原题。写入embedding_tokens及embedding_header_shortened；原生encode前再次按实际model.tokenizer/max_seq_length校验，超长查询同样拒绝。无tokenizer明确失败，不用字符估算冒充准确预算。空内容清理不需要加载tokenizer。

相同合成输入经真实本机BGE编码，得到512/138token两块、各1024维、范数1，正文完整保留；CPU两线程加载与编码15.415s。这验证输入完整性，不证明召回或回答语义指标提高。代价是多一个向量/重复标题，极长标题前缀可能降低尾部标题检索能力；新规则只影响后续任务，不自动重写旧集合。并发首次模型加载用锁保护，4个模拟并发构造从4份变1份；没有把该测试当成真实多线程推理吞吐保证。

## 证据和读路径

工具输出原来丢掉source_fingerprint；现在保留。SQLAlchemy identity map缓存对象也可能让旧正文通过校验，因此Agent、两步RAG、候选检索及详情查询刷新当前SQL对象。日期增强过滤失败时只留空，删除跨用户全表回退。缺集合的检索只get，不再get_or_create；空索引不加载大模型，候选模式缺索引明确error。

刷新对象不等于跨存储事务或MySQL跨事务实时快照，未对真实MySQL/多进程PersistentClient缓存可见性验收。老集合无指纹的兼容限制仍在。

## 工具等待与资源

原实现ThreadPoolExecutor的with退出会等待任务，30ms超时复现实测301ms才返回。新实现共享有界池，最多4个在途任务；超时工作真正结束才释放槽，已满立即返回capacity错误，不无限排队/增线程。文件数据库Engine创建独立Session，不把请求Session送给遗留线程；未提交的调用方变更被拒绝，不隐式flush/commit。内存SQLite、StaticPool及Connection绑定同步执行，明确不承诺该分支的硬等待时限。

请求可以先返回超时，但不能杀死正在运行的线程；停服务也不能保证强制终止所有底层工作。生命周期关闭池并取消未启动任务，容量跨池重建保持约束。若需要硬进程取消，需另设计独立存储/模型进程与序列化成本，而不是仅用shutdown(wait=False)继续共享会话。参考[Python3.12 §Executor.shutdown/Future.cancel](https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Executor.shutdown)及[SQLAlchemy2.1 §Is the Session thread-safe?](https://docs.sqlalchemy.org/en/21/orm/session_basics.html#is-the-session-thread-safe-is-asyncsession-safe-to-share-in-concurrent-tasks)。

## 提供方

开发模式也默认不读取个人cc-switch；allow_personal_ai_config默认false，只有明确开启且处于development才兼容该来源，production始终不启用。显式服务/用户配置仍优先，缺key保持未配置。本轮没有修改凭据文件或启用旧网关。默认DeepSeek兼容URL/model ID保持此前已修正值。

## 复现

从backend使用已验证Python3.12环境：

```text
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
python -m mypy --follow-imports=silent --ignore-missing-imports app/models/index_job.py app/services/index_jobs.py app/services/index_worker.py app/services/evidence_freshness.py app/services/embedding_input.py app/services/tool_executor.py
python -m compileall -q app eval
python -m eval.check_artifact_policy
```

完整端到端deadline、生成模型匹配token计数、长期推理负载及远端CI仍未验收；严格Agent大详情/历史超预算仍会明确error，没有新增自动上下文压缩策略。
