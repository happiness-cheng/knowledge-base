# 原生检索到真实回答：5题有限验收

## 这次补上了哪段证据

10/14 的框架对照使用冻结词项快照，不能证明真实 BGE 检索到生成的链路。本次使用原16篇技术笔记，通过业务切片与完整输入保护写入229块真实归一化 BGE 向量，经 Chroma HTTP、SQL 所有权/版本核验，直接调用 `run_langchain_rag`，再调用真实 DeepSeek。

不按 gold 挑片段，不把整篇原文补给模型。当前原生检索最多3个父文档、每文档2块；rewrite、reranker和额外judge均未启用。认证身份由验收端固定为临时用户1，不从问题中提取。

这是 **LC业务函数的原生检索到生成验收**，不包含浏览器、登录/聊天HTTP路由、默认Agent backend、独立writer进程或全部36题。临时SQL和独立临时Chroma服务未触碰原库、原索引或凭据文件内容。

## 实际结果

用户新增授权最多5次物理请求；实际5次，均HTTP200，每题1次，无重试、改写或在线裁判。请求模型ID为 `deepseek-flash`，固定官方兼容端点，非思考模式；只读取显式凭据文件，不读取个人工具默认网关。实际JSON最长7851字符（上限16000），输出合计456 token（每次上限600）。这5次新预算已用完。

| 问题 | 系统输出 | 按实际可见证据复核 |
|---|---|---|
| CR02：SETNX返回值及基本锁 | supported，引用1013 | False/True、锁键存在性和EXPIRE描述均来自可见笔记；不作完整生产锁安全证明 |
| CR07：线程为何比独立进程开销小 | supported，引用1001 | 创建/撤销资源、CPU切换与寄存器、通信段进入上下文，解释有对应支持 |
| CR13：过期时间与锁释放 | supported，引用1008/1013 | 过期删除与锁键含义分别有证据；最后一句是基本锁模型下的组合推论，不能扩大为任意故障下互斥保证 |
| CR19：资源分配与调度单位 | supported，引用1001 | 两个定义都在可见证据中，没有互换 |
| CR26：yield局部变量保存/恢复 | not_found，无引用 | 候选是Java LRU、Redis与OS代码，未支持所问实现；用户可见输出限定为“本次检索未找到” |

复核由**主代理源感知逐事实审查**完成，不是独立人工双审。CR02预先rubric写0/1，实际可见笔记写False/True：按笔记中的失败/成功含义审查并公开这一解释，不把忠实于笔记的回答判错，也没有据此验证Redis协议或各客户端的返回类型。CR26审查的是服务端归一化后的用户可见拒答，不推断未保存的原始模型JSON字段。

原始观察与答案见[脱敏投影报告](evidence/native-rag-deepseek-20261017.json)，每个事实对应的可见原文见[逐事实复核](evidence/native-rag-review-20261017.json)。公开投影只去掉本地临时目录，保留原报告hash、实际结果、证据与逐请求记录。

## 提示、用量和耗时如何核对

从实际观察记录重建系统提示、问题、日期和证据JSON，与HTTP transport记录的提示hash逐条核对，5次全部一致；不能用“完整原文里有”替代“本次模型实际看见了”。[审计记录](evidence/native-rag-audit-20261017.json)保留逐题字符数、HTTP状态、来源ID和用量。

| 项目 | 本次观察 |
|---|---|
| 普通输入token / 缓存读取 / 缓存创建 | 10023 / 0 / 0 |
| 输出token | 456 |
| 查询链路P50 / P95，n=5 | 1468.0 / 1678.4 ms |
| 加载模型及16篇索引构建 | 285.063 s，229块，CPU4线程 |

查询耗时包含查询编码、Chroma、SQL核验、LC、真实提供方请求和输出契约处理，不含前面的索引构建。P95按5个样本排序线性插值，不是长期负载SLA；用量来自提供方响应，不是账单。日期metadata来自临时SQL的创建时间，不代表原笔记发布日期，本批也不验证时效问答。

## 可以与旧批次作什么比较

旧词项快照的CR07缺关键段，却仍输出supported及合法引用，人工式复核发现了越界内容。本轮实际原生上下文含关键段，回答也有对应支持。这提供一个具体实例：**引用校验只约束来源ID，事实支持还依赖真正进入提示的内容。**

两个批次的检索、切片、父文档数量、上下文和日期并非完全匹配，不能把结果变化单独归因为BGE或LangChain，也不报告受控的提升百分点。此前的检索矩阵数据仍保留自己的实验口径。

5题全部是原题集的development样例，由看过源文的agent编写。4个supported和1个not_found不是系统准确率；本报告的 `semantic_accuracy=null`，独立题集和独立人工语义验收仍pending。没有新增调参或把这些题包装成盲测。

## 便携入口与复现

[run_native_rag_validation.py](../backend/eval/run_native_rag_validation.py)默认只输出计划，不导入应用、不加载模型、不读凭据，也不访问网络：

```text
# backend目录，已有约束依赖的Python3.12环境
python -X utf8 -m eval.run_native_rag_validation
python -X utf8 -m eval.offline_tests --empty-model-cache tests/test_native_rag_validation.py -q --tb=short
python -X utf8 -m eval.offline_tests --empty-model-cache tests -q --tb=short
# 本轮完整回归：450 passed，5条既有warnings，86.17s
```

要复现真实BGE预检，替换下面的路径为已有缓存和新报告路径；没有模型下载或真实生成请求：

```text
python -X utf8 -m eval.run_native_rag_validation --prepare --model-path "<已有BGE snapshot绝对路径>" --hf-home "<已有HF缓存根>" --output "<新的本地报告路径>"
```

只有取得**另一次**外发与请求预算授权后，才可运行真实回答；CLI开关不代替用户授权：

```text
python -X utf8 -m eval.run_native_rag_validation --allow-network --new-request-budget 5 --credentials-file "<显式DeepSeek凭据文件>" --model-path "<已有BGE snapshot绝对路径>" --hf-home "<已有HF缓存根>" --output "<新的本地报告路径>"
```

输出状态和日志保留到报告旁的新目录，不自动覆盖旧报告。实际测量来自外部工作目录中的冻结脚本，便携入口调整仓库路径定位与import排序，并内置拒绝覆盖旧报告及排他创建保护（测量运行前由外层检查保证新路径）；两个源码hash、差异说明在报告中，未冒充又执行了5次真实请求。便携入口已验证默认计划、越权预算拒绝、凭据读取前拒绝与临时服务退出，9个新增离线检查和原回归均通过。
