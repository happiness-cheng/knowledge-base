# Retrieval regression — frozen-dense

- generated_at: 2026-11-24T17:42:25.590840+00:00
- dataset_sha256: `c8535363fb25dca97ca79310024cabb4be6c03c14addc40bfc91621e7c9ebb6a`
- manifest_sha256: `8d406518016dc136f5f615ac3e3efde20fe14a6a2ee2078490339105ed5c2b7b`
- top_k: 3
- retrieval_quality_measured: True

| metric | value |
|---|---:|
| hit@1 | 0.8889 |
| hit@3 | 1.0000 |
| mrr | 0.9444 |
| evidence_coverage | 0.7778 |
| all_evidence_rate | 0.7407 |
| ndcg@10 | 0.9447 |

- positive_cases: 27
- negative_cases: 9
- p50_ms: 0.001
- p95_ms: 0.001

## Failure buckets

- all_evidence: 20
- negative: 9
- node_hit_no_evidence: 5
- partial_evidence: 2

## Per split

| split | n | hit@3 | evidence_coverage |
|---|---:|---:|---:|
| heldout | 12 | 1.0000 | 0.5833 |
| development | 15 | 1.0000 | 0.9333 |
