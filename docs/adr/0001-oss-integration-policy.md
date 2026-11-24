# ADR 0001：RAG 项目的开源组件接入政策

- 状态：已接受
- 日期：2026-11-25
- 决策者：项目维护者
- 相关计划：`docs/superpowers/plans/2026-11-25-rag-oss-integration.md`

## 背景

项目已经具备 LangChain 严格 RAG、dense/BM25/RRF/rerank/rewrite 候选、冻结评测集和持久索引。
继续“按 star 数接入框架”会重复建设、增加依赖冲突，并让面试官无法判断每个组件解决了什么问题。

## 决策

任何新增开源组件必须同时满足以下 5 条，才进入实施：

1. **具体缺口**：能指向当前代码/数据无法解决的一个问题，而不是“别人都在用”。
2. **可测量收益**：有冻结数据、基线、对照和失败案例；不能只用“接入成功”作为验收。
3. **依赖可隔离**：不破坏现有 `langchain-core==1.6.10` / Python 3.12 验证环境；重依赖放独立 venv、子进程或容器。
4. **失败可回退**：有 feature flag 或显式 backend；组件故障不阻塞主链路。
5. **可解释代价**：记录延迟、token、成本、运维复杂度和新增攻击面。

## 采纳

| 组件 | 版本（计划时） | 缺口 | 隔离方式 | 验收 |
|---|---|---|---|---|
| Ragas | 0.4.4 | 自研 judge 不是标准 RAG 指标 | 独立 `requirements-eval-ragas.txt` + venv，只读写 JSONL | 与自研 judge 对照 + bootstrap CI |
| Langfuse | SDK 5.2.x / server 4.85.x | 无跨请求 trace/成本面板 | 默认 no-op，Cloud 或可选 compose | span 树、脱敏、故障不阻塞 |
| LangGraph | 1.2.24 | Agent 无 checkpoint/恢复 | 生产依赖，显式 backend | 与 custom 的 parity + resume 测试 |
| Docling | 2.152.0 | 无 PDF/版面/页码 | 独立 CLI/服务 + 可选依赖 | PDF 导入 + 页码引用 + fallback |

## 拒绝

| 组件 | 拒绝理由 |
|---|---|
| RAGFlow | 原判断为“完整平台，与现有检索/切片/索引重复”；2026-11-25 用户明确选择直接接入 RAGFlow，作为生产检索/存储后端，见 [ADR 0002](0002-ragflow-backend.md)。本行保留为历史决策，不再作为拒绝依据。 |
| LlamaIndex | 与 LangChain 双抽象重复；没有当前缺口需要它 |
| Qdrant | Chroma 已满足；迁移会推翻已有 HTTP 进程边界与索引一致性验证 |
| DeepEval | 与 Ragas 重叠；仅作为 Ragas 适配失败时的备选 |
| Unstructured | Docling 覆盖 PDF/Office，且 Windows 安装更简单；不同时维护两套解析器 |
| Microsoft GraphRAG / LightRAG | 需要实体/社区索引，成本高；现有邻居扩展实验已显示负结果，暂不引入 |

## 兼容性约束

- `langchain-anthropic` 1.7.x 要求 `langchain-core>=1.8.4`，与当前 `1.6.10` 不兼容；不为了“更正统”升级 core。
- LangGraph 节点直接调用现有 `AIClient.chat_with_tools`，不引入新的 provider 适配。
- Ragas 依赖 `langchain`/`langchain-community`/`datasets`，不能进生产 requirements。
- Docling 模型重、解析不可信文件有攻击面，不能进主进程。

## 后果

- 正面：每个新增组件都能被追问“为什么、代价、失败怎么办”；依赖冲突被隔离；主链路可回退。
- 负面：多维护一个 eval venv、一个可选 Docling 服务；LangGraph 需要 parity 测试。
- 不做：不追求组件数量；不把 star 数写进验收标准；不把“接入成功”写成“质量提升”。

## 复审

每个组件完成 P1–P4 验收后更新本 ADR；若对照无收益，保留为候选或删除，并在 README 记录负结果。