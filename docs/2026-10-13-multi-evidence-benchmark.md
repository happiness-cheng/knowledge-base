# 多文档、多区间 gold 的评测契约

本次扩展为后续 30–40 题评测提供多证据输入与计分能力。它不生成题集、不调用在线模型、不读取私人语料或真实数据库，也不表示 RAG 质量已经提升。原七列用例、旧 `BenchmarkCase` 字典和单 gold 指标保持兼容。

## 输入

旧七列格式仍为 `[case_id, node_id, note_type, query_source, question, head, tail]`。旧字典仍可用 `gold_node_id`、`evidence_head`、`evidence_tail`。

新格式使用 `gold_evidence`：

```json
{
  "cases": [
    {
      "case_id": "M01",
      "question": "批准后如何执行，结果不确定时如何恢复？",
      "note_type": "multi_document",
      "query_source": "authored",
      "gold_evidence": [
        {"node_id": 7, "head": "批准后执行", "tail": "记录执行标识"},
        {"node_id": 7, "head": "结果未知时停止重试"},
        {"node_id": 8, "head": "通过对账确认结果", "tail": "恢复状态"}
      ]
    },
    {"case_id": "N01", "question": "语料中没有的工资信息", "note_type": "negative"}
  ]
}
```

- 每个 `EvidenceTarget(node_id, head, tail=None)` 要求正整数文档 ID（不接受布尔值）、非空 head 和字符串或 null 的 tail。
- `gold_evidence` 的语义是 **全部必需**，不表示多个等价候选。可省略所有旧 gold 字段；非空 `gold_evidence` 与任何非 null 的旧 gold 字段混用会报错。
- Python 输入中的列表和字典被复制为冻结的 `EvidenceTarget` tuple，避免后续修改 gold。按 `(node_id, 去空白 head, 去空白 tail)` 去重；同文档的不同区间分别保留。
- 不提供 gold 的用例为负例。`gold_evidence=[]` 与旧字段均为 null 时同样为负例；需在题集审查时确认这确实是无法回答的问题。
- 任一必需文档或有序锚点不在冻结 corpus 内，整题标记 `invalid_gold`，记录 `invalid_gold_targets`，不进入执行器。它不会被当作检索失败。

## 计分与分母

文档排序沿用原评测口径：对实际 `retrieved` 中的 `node_id` 按出现顺序去重。多块来自同一文档时，该文档只占一个排名。这里的 K 是去重后的父文档数，与原始向量块 K 分开解释。

| 字段 | 逐题含义 | summary 含义 |
|---|---|---|
| `hit_at_1`、`hit_at_3` | 前 K 文档命中任一必需文档 | 有效正例均值，单 gold 口径不变 |
| `reciprocal_rank` / `mrr` | 首个必需文档的倒数排名 | 有效正例均值，单 gold 口径不变 |
| `document_recalled_at_1/3` | 前 K 文档中召回的必需文档数 | 有效正例分子总和 |
| `document_targets` | 唯一必需文档数 | 有效正例分母总和 |
| `document_recall_at_1/3` | 召回文档数 / 必需文档数 | 逐题比例的均值（macro） |
| `evidence_covered` | 实际上下文覆盖的唯一证据区间数 | 有效正例分子总和 |
| `evidence_targets` | 唯一必需证据区间数 | 有效正例分母总和 |
| `evidence_coverage` | 覆盖区间数 / 必需区间数 | 分子总和 / 分母总和（micro） |
| `evidence_all_covered` | 每个必需区间均覆盖时为 1 | 所有证据齐全的有效正例比例 |
| `evidence_in_context` | 与 `evidence_all_covered` 相同；负例沿用原值 0 | 有效正例均值，单 gold 口径不变 |

Hit@K 不是多文档 Recall@K。例如两个必需文档只召回一个时，Hit@3=1，document Recall@3=1/2。summary 中 `document_recalled_at_3 / document_targets` 可另算 micro Recall，不能与已给出的 macro Recall 混称。

证据覆盖要求对应文档的 **同一实际返回块** 中存在按顺序排列的完整 head/tail 锚点；仅删除空白后匹配，不做语义推断。同一文档的两个不同区间可分别由两个块覆盖，但一个区间的 head/tail 分别落在两个块时，该区间不算覆盖。重复返回同一块不会增加覆盖分子。Corpus 只用来校验 gold，不能把 corpus 内容补入检索上下文来计分或构造答案。

有效正例的执行异常保留文档和证据分母，分子记 0。负例不参与 Recall/证据覆盖分母；没有正例时比例为 null，分子/分母计数为 0。无效 gold 整题排除。分层报告使用相同规则。

拒答与引用继续沿用旧检查：严格 `refusal_rate` 要求显式拒答且无引用；`refusal_detected_rate` 和 `refusal_with_citations_rate` 分开报告，带背景引用的拒答进入人工复核。检索模式不报告答案类指标。引用 ID 合法与证据齐全都不能代替人工判断答案正确性。

任一记录缺失 input 或 output usage，其 `usage_status` 为 `unknown`；各方向 token 总量分别沿用原规则，任一有效用例缺少该方向用量时为 null。所有有效用例两个方向用量齐全才报告总 `usage_status=complete`。

## 报告兼容

报告保留 `schema_version=2`，增量增加上述字段、`gold_mode`、`gold_document_ids`、`gold_evidence` 和 `metric_definitions`。旧字段没有移除；旧单 gold 的数值口径没有调整。Markdown 逐题表新增文档 Recall、证据分子/分母与 all-covered，另列指标定义；渲染器仍接受没有新字段的历史 schema 2 报告。

## 本次验证

在 `backend` 目录实际执行隔离入口，阻止读取真实配置和外部网络，复用原环境的 site-packages：

```powershell
& 'C:\Users\陈独秀\agent-career-plan-20261012\python\cpython-3.14.8-windows-x86_64-none\python.exe' 'C:\Users\陈独秀\agent-career-plan-20261012\offline_knowledge_tests.py' --site-packages 'C:\Users\陈独秀\knowledge-base\backend\venv\Lib\site-packages' tests/test_benchmark.py -q --tb=short
```

| 垂直切片 | RED | GREEN |
|---|---|---|
| 新输入、冻结与兼容 | 3 failed / 11 passed，缺少 EvidenceTarget | 14 passed |
| 多证据判定、Recall、覆盖与失败分母 | 8 failed / 14 passed，multi 被误判负例且缺指标 | 22 passed |
| 报告展示 | 1 failed / 25 passed，未展示证据分子/分母 | 26 passed |

最终单文件回归为 **26 passed / 1 warning**。警告是隔离入口预导入 anyio 引起的 pytest assertion rewrite 提示。原负例、预算错误和真实 Agent 观察适配测试仍通过；新增真实 Agent 路径测试确认未召回 gold 没有进入模型请求，也没有增加 `retrieved` 内容或证据得分。未修改 `run_benchmark.py`，未引入新依赖。

随后把同一命令的测试参数扩为 `tests/test_benchmark.py tests/test_bounded_eval_client.py -q --tb=short`，相关回归为 **29 passed / 1 warning**；两处 Python 文件的 AST 语法检查均通过。全新 Python 3.12 环境、项目全量测试与整体验收由主任务统一执行，本记录不宣称它们已经通过。

这批是人工机制 fixture，证明计分契约，不构成 30–40 题真实质量报告。后续需冻结语料/题集版本、审查全部必需 gold、记录候选检索配置、运行获授权的真实检索和模型、人工复核答案与引用归属，再形成项目结果证据。
