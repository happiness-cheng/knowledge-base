# Knowledge benchmark

```json
{
  "variant": "rrf_2048_neighbors_0",
  "llm_called": false,
  "neighbors": false,
  "context_budget_bge_tokens": 2048,
  "baseline_report_sha256": "771213bf8f751ca6e054f8e5af0ba527a117c7947caab4554ca27c903333e5ec",
  "dataset_hash": "c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a",
  "corpus_manifest_hash": "8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b",
  "latency_basis": "context packing only; no embedding/reranker/model generation",
  "code_hashes": {
    "eval/context_candidates.py": "aaf8a42f0aa0262d4e404e8dffe69e2e381ad749b6044036db2cf9f16a9dfdc7",
    "eval/run_context_matrix.py": "b4e6aafa887de71a5eb2ac0908c92d6af3fab126a67bc663d83e0bf8c32b67d9"
  }
}
```

| 指标 | 结果 |
|---|---|
| total_cases | 36 |
| valid_cases | 36 |
| invalid_cases | 0 |
| execution_errors | 0 |
| positive_cases | 27 |
| negative_cases | 9 |
| hit_at_1 | 0.9629629629629629 |
| hit_at_3 | 1.0 |
| mrr | 0.9814814814814815 |
| evidence_in_context | 0.8148148148148148 |
| document_recall_at_1 | 0.8518518518518519 |
| document_recall_at_3 | 0.9814814814814815 |
| document_recalled_at_1 | 26 |
| document_recalled_at_3 | 32 |
| document_targets | 33 |
| evidence_covered | 37 |
| evidence_targets | 42 |
| evidence_coverage | 0.8809523809523809 |
| evidence_all_covered | 0.8148148148148148 |
| refusal_rate | 0.0 |
| refusal_detected_rate | 0.0 |
| refusal_with_citations_rate | 0.0 |
| citation_valid_rate | 1.0 |
| latency_p50_ms | 75.71 |
| latency_p95_ms | 96.373 |
| total_input_tokens | None |
| total_output_tokens | None |
| usage_status | unknown |

| case | status | rank | evidence | citations | docs@1 | docs@3 | evidence spans | all covered |
|---|---|---|---|---|---|---|---|---|
| CR01 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR02 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR03 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR04 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR05 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR06 | ok | None | 0 | True | None | None | 0/0 | None |
| CR07 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR08 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR09 | ok | 1 | 0 | True | 1.0 | 1.0 | 0/1 | 0 |
| CR10 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR11 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR12 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR13 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR14 | ok | 1 | 0 | True | 0.5 | 0.5 | 1/2 | 0 |
| CR15 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR16 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR17 | ok | 1 | 0 | True | 0.5 | 1.0 | 1/2 | 0 |
| CR18 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR19 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR20 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR21 | ok | 1 | 0 | True | 1.0 | 1.0 | 1/2 | 0 |
| CR22 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR23 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR24 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR25 | ok | None | 0 | True | None | None | 0/0 | None |
| CR26 | ok | None | 0 | True | None | None | 0/0 | None |
| CR27 | ok | None | 0 | True | None | None | 0/0 | None |
| CR28 | ok | None | 0 | True | None | None | 0/0 | None |
| CR29 | ok | None | 0 | True | None | None | 0/0 | None |
| CR30 | ok | None | 0 | True | None | None | 0/0 | None |
| CR31 | ok | 1 | 1 | True | 1.0 | 1.0 | 1/1 | 1 |
| CR32 | ok | 1 | 0 | True | 1.0 | 1.0 | 0/1 | 0 |
| CR33 | ok | 2 | 1 | True | 0.0 | 1.0 | 1/1 | 1 |
| CR34 | ok | 1 | 1 | True | 1.0 | 1.0 | 2/2 | 1 |
| CR35 | ok | None | 0 | True | None | None | 0/0 | None |
| CR36 | ok | None | 0 | True | None | None | 0/0 | None |

| 指标口径 | 定义 |
|---|---|
| hit_at_1 | 有效正例的任一必需文档出现在首个去重文档；单 gold 保留原口径 |
| hit_at_3 | 有效正例的任一必需文档出现在前 3 个去重文档；不等于多文档 Recall |
| mrr | 有效正例中首个必需文档的倒数排名均值；单 gold 保留原口径 |
| document_recall_at_1 | 逐题前 1 个去重文档召回的必需文档数 / 必需文档总数，再对有效正例取均值（macro） |
| document_recall_at_3 | 逐题前 3 个去重文档召回的必需文档数 / 必需文档总数，再对有效正例取均值（macro） |
| document_recalled_at_1 | 有效正例前 1 文档的召回数总和；与 document_targets 构成 micro 分子/分母 |
| document_recalled_at_3 | 有效正例前 3 文档的召回数总和；与 document_targets 构成 micro 分子/分母 |
| evidence_coverage | 实际 retrieved 内容中覆盖的唯一证据区间数 / 有效正例唯一证据区间总数（micro） |
| evidence_all_covered | 所有必需证据区间均覆盖的有效正例比例；evidence_in_context 的兼容别名 |
| denominators | invalid_gold 整题排除且不执行；execution_error 保留在有效正负例和证据/文档分母中 |

机械证据与引用检查不等于答案正确性；需人工复核
负例 refused 来自执行器的显式判定，报告必须注明其规则
refusal_rate 保留旧严格无引用条件；detected / with_citations 分开观察，不等于人工语义正确率
多证据为全部必需；文档 Recall 与证据覆盖分开统计，未召回证据不能从 gold 正文补入
文档排名沿用去重父文档口径；不代表原始向量块的 Recall@K
用量缺失为 unknown / null；离线桩结果不代表模型或真实检索质量
