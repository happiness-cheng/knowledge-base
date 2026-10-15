# Knowledge benchmark

```json
{
  "mode": "retrieval",
  "frozen_at": "2026-10-13",
  "measured_at_utc": "2026-10-14T04:49:42.417804+00:00",
  "dataset_hash": "c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a",
  "corpus_manifest_hash": "8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b",
  "device": "cpu",
  "threads": 4,
  "llm_called": false,
  "model_quality_measured": false,
  "retrieval_quality_measured": true,
  "network": "socket connections blocked; cached snapshots only",
  "context_budget_bge_tokens": 1536,
  "user_id": 1,
  "evaluation_stage": "packed_context; candidate-pool Recall retained separately in steps",
  "latency_basis": "query encoding + context packing + shared real20-pair inference when reranked; excludes load/index; pool5/10 cache time is not inference",
  "code_hashes": {
    "eval/benchmark.py": "5265eb0f9774e0233f7a87c128b855897dbb5b7ac9adb885994885f5fb9890b2",
    "eval/core_corpus.py": "8cdbc9db44d934dce0749ecf8b7ebe74a2beae7bb04292eb5f019bf7d6403674",
    "eval/retrieval_candidates.py": "ff31052ec747ddcfb8d569b644fa8bcafc393cdaecf94e27ab9b49f493f35e89",
    "eval/run_retrieval_matrix.py": "aca20de695b2dbca9f4f30c92f07a3b7b6477dc4113f72e82c3e74fdbd349e01",
    "app/utils/markdown_cleaner.py": "1109053d4e27caeb23eb12449e9fff6204c48fcd0173ce21d7eecc82bc034bc0"
  },
  "runtime_versions": {
    "torch": "2.14.1",
    "sentence-transformers": "6.1.0",
    "transformers": "5.19.0",
    "numpy": "2.5.4",
    "rank-bm25": "0.2.2",
    "jieba": "0.42.1"
  },
  "embedding_revision": "79e7739b6ab944e86d6171e44d24c997fc1e0116",
  "reranker_revision": "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
  "embedding_load_ms": 417.472799999814,
  "chunk_embedding_ms": 424706.0722000006,
  "bm25_build_ms": 986.4886999994269,
  "chunk_config": {
    "strategy": "heading",
    "body_tokens": 480,
    "overlap_tokens": 0,
    "model_limit": 512
  },
  "chunk_count": 221,
  "rrf_k": 60,
  "rrf_tuning_development_only": {
    "20": {
      "total_cases": 17,
      "valid_cases": 17,
      "invalid_cases": 0,
      "execution_errors": 0,
      "positive_cases": 15,
      "negative_cases": 2,
      "hit_at_1": 0.9333333333333333,
      "hit_at_3": 1.0,
      "mrr": 0.9666666666666667,
      "evidence_in_context": 0.9333333333333333,
      "document_recall_at_1": 0.8333333333333334,
      "document_recall_at_3": 0.9666666666666667,
      "document_recalled_at_1": 14,
      "document_recalled_at_3": 17,
      "document_targets": 18,
      "evidence_covered": 24,
      "evidence_targets": 25,
      "evidence_coverage": 0.96,
      "evidence_all_covered": 0.9333333333333333,
      "refusal_rate": null,
      "refusal_detected_rate": null,
      "refusal_with_citations_rate": null,
      "citation_valid_rate": null,
      "latency_p50_ms": 67.112,
      "latency_p95_ms": 88.771,
      "total_input_tokens": null,
      "total_output_tokens": null,
      "usage_status": "unknown"
    },
    "60": {
      "total_cases": 17,
      "valid_cases": 17,
      "invalid_cases": 0,
      "execution_errors": 0,
      "positive_cases": 15,
      "negative_cases": 2,
      "hit_at_1": 0.9333333333333333,
      "hit_at_3": 1.0,
      "mrr": 0.9666666666666667,
      "evidence_in_context": 0.9333333333333333,
      "document_recall_at_1": 0.8333333333333334,
      "document_recall_at_3": 0.9666666666666667,
      "document_recalled_at_1": 14,
      "document_recalled_at_3": 17,
      "document_targets": 18,
      "evidence_covered": 24,
      "evidence_targets": 25,
      "evidence_coverage": 0.96,
      "evidence_all_covered": 0.9333333333333333,
      "refusal_rate": null,
      "refusal_detected_rate": null,
      "refusal_with_citations_rate": null,
      "citation_valid_rate": null,
      "latency_p50_ms": 55.962,
      "latency_p95_ms": 70.305,
      "total_input_tokens": null,
      "total_output_tokens": null,
      "usage_status": "unknown"
    },
    "120": {
      "total_cases": 17,
      "valid_cases": 17,
      "invalid_cases": 0,
      "execution_errors": 0,
      "positive_cases": 15,
      "negative_cases": 2,
      "hit_at_1": 0.9333333333333333,
      "hit_at_3": 1.0,
      "mrr": 0.9666666666666667,
      "evidence_in_context": 0.9333333333333333,
      "document_recall_at_1": 0.8333333333333334,
      "document_recall_at_3": 0.9666666666666667,
      "document_recalled_at_1": 14,
      "document_recalled_at_3": 17,
      "document_targets": 18,
      "evidence_covered": 24,
      "evidence_targets": 25,
      "evidence_coverage": 0.96,
      "evidence_all_covered": 0.9333333333333333,
      "refusal_rate": null,
      "refusal_detected_rate": null,
      "refusal_with_citations_rate": null,
      "citation_valid_rate": null,
      "latency_p50_ms": 64.232,
      "latency_p95_ms": 85.176,
      "total_input_tokens": null,
      "total_output_tokens": null,
      "usage_status": "unknown"
    }
  },
  "query_prefix": "为这个句子生成表示以用于检索相关文章：",
  "embedding_normalized": true,
  "candidate_pool": 20,
  "original_k3_output": "C:\\Users\\陈独秀\\knowledge-base\\backend\\eval\\reports\\retrieval-matrix\\20261014T044942416805Z",
  "resumed_at_utc": "2026-10-14T05:07:06.280477+00:00",
  "baseline_code_hashes": {
    "eval/benchmark.py": "5265eb0f9774e0233f7a87c128b855897dbb5b7ac9adb885994885f5fb9890b2",
    "eval/core_corpus.py": "8cdbc9db44d934dce0749ecf8b7ebe74a2beae7bb04292eb5f019bf7d6403674",
    "eval/retrieval_candidates.py": "ff31052ec747ddcfb8d569b644fa8bcafc393cdaecf94e27ab9b49f493f35e89",
    "eval/run_retrieval_matrix.py": "af7f62345bf8de062435e01080a45b14fb05ac42c166444046b728f2c3ab7ee1",
    "app/utils/markdown_cleaner.py": "1109053d4e27caeb23eb12449e9fff6204c48fcd0173ce21d7eecc82bc034bc0"
  },
  "variant": "rrf_off_10",
  "reranker_pool": 10,
  "reranker_enabled": false,
  "control_postprocess_code_hash": "aca20de695b2dbca9f4f30c92f07a3b7b6477dc4113f72e82c3e74fdbd349e01"
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
| evidence_in_context | 0.7777777777777778 |
| document_recall_at_1 | 0.8518518518518519 |
| document_recall_at_3 | 0.9629629629629629 |
| document_recalled_at_1 | 26 |
| document_recalled_at_3 | 31 |
| document_targets | 33 |
| evidence_covered | 35 |
| evidence_targets | 42 |
| evidence_coverage | 0.8333333333333334 |
| evidence_all_covered | 0.7777777777777778 |
| refusal_rate | None |
| refusal_detected_rate | None |
| refusal_with_citations_rate | None |
| citation_valid_rate | None |
| latency_p50_ms | 379.033 |
| latency_p95_ms | 419.837 |
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
| CR14 | ok | 1 | 0 | True | 0.5 | 0.5 | 0/2 | 0 |
| CR15 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR16 | ok | 1 | 1 | True | 0.5 | 1.0 | 2/2 | 1 |
| CR17 | ok | 1 | 0 | True | 0.5 | 1.0 | 1/2 | 0 |
| CR18 | ok | 1 | 0 | True | 0.5 | 0.5 | 1/2 | 0 |
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
