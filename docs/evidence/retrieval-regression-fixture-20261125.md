# Retrieval regression — fixture

- generated_at: 2026-11-24T17:33:41.580557+00:00
- dataset_sha256: `c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a`
- manifest_sha256: `8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b`
- top_k: 3
- retrieval_quality_measured: False

| metric | value |
|---|---:|
| hit@1 | 0.8889 |
| hit@3 | 1.0000 |
| mrr | 0.9444 |
| evidence_coverage | 0.4074 |
| all_evidence_rate | 0.2963 |
| ndcg@10 | 0.9554 |

- positive_cases: 27
- negative_cases: 9
- p50_ms: 13.381
- p95_ms: 14.912

## Failure buckets

- all_evidence: 8
- negative: 9
- node_hit_no_evidence: 13
- partial_evidence: 6

## Per split

| split | n | hit@3 | evidence_coverage |
|---|---:|---:|---:|
| heldout | 12 | 1.0000 | 0.3333 |
| development | 15 | 1.0000 | 0.4667 |
