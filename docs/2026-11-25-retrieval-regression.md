# 检索质量回归：Hit@k、证据覆盖与门禁

- 日期：2026-11-25
- 入口：[run_retrieval_regression.py](../backend/eval/run_retrieval_regression.py)
- 纯指标/后端：[retrieval_regression.py](../backend/eval/retrieval_regression.py)
- 冻结题集：`backend/eval/fixtures/core-rag-20261013.json`（36 题）
- 语料 manifest：`backend/eval/fixtures/core-rag-corpus-20261013.json`（16 篇）

## 为什么只评检索层

生成答案的质量会掩盖检索问题：文档 Hit@3 可能已经是 1.0，但答案需要的证据区间仍
被挤出上下文。这个入口只测检索层，不调用生成模型，回答质量仍由现有 benchmark /
真实生成验收单独负责。

## 指标

| 指标 | 定义 | 分母 |
|---|---|---|
| Hit@1 / Hit@3 | top1/top3 的唯一 node 是否含任一 gold node | 正例 |
| MRR | 首个 gold node 排名的倒数 | 有 gold 且被检索到的正例 |
| evidence_coverage | 每个 gold `EvidenceTarget` 的有序 head/tail 是否出现在对应 node 的返回内容 | 全部 gold target |
| all_evidence_rate | 一题的所有 gold target 是否都覆盖 | 正例 |
| nDCG@10 | 以 gold node 为二值相关，按唯一 node 排名计算 | 正例 |
| p50/p95 latency | 单题检索墙钟 | 全部用例 |

失败桶：

- `not_retrieved`：top_k 没有 gold node；
- `node_hit_no_evidence`：命中了 gold node，但 head/tail 不在返回内容；
- `partial_evidence`：多 gold 题只覆盖一部分；
- `all_evidence`：全部覆盖；
- `negative`：无 gold 的负例，不计入正例指标。

## 后端

| `--backend` | 用途 | 是否代表真实质量 |
|---|---|---|
| `fixture` | 确定性词项检索，CI plumbing / 报告 schema | **否** |
| `chroma` | 调 `rag_service.retrieve_relevant_nodes`，需要已建索引/模型 | 是（检索层） |
| `ragflow` | 调 `ragflow_retrieval.retrieve_for_user`，需要 RAGFlow 配置 | 是（检索层） |

fixture 的 `retrieval_quality_measured=false`，报告里明确标注；不能拿它跟
Chroma/RAGFlow 的真实分数混比。

## 运行

```powershell
cd backend

# CI/本地快速检查：不加载模型、不联网
python -m eval.run_retrieval_regression --backend fixture `
  --output ..\docs\evidence\retrieval-regression-fixture-20261125.json

# 真实 Chroma：需要已建好 user 1 的索引
python -m eval.run_retrieval_regression --backend chroma --user-id 1 `
  --output ..\docs\evidence\retrieval-regression-chroma-20261125.json

# 真实 RAGFlow：需要 RAGFLOW_BASE_URL/API_KEY 和已同步文档
python -m eval.run_retrieval_regression --backend ragflow --user-id 1 `
  --output ..\docs\evidence\retrieval-regression-ragflow-20261125.json

# 与基线比较；有指标下降时退出码 2
python -m eval.run_retrieval_regression --backend fixture `
  --output "$env:TEMP\retrieval.json" `
  --baseline eval\fixtures\retrieval-baseline-fixture-20261125.json --gate
```

## 当前 fixture 基线

`eval/fixtures/retrieval-baseline-fixture-20261125.json` 来自冻结 36 题：

| 指标 | 值 |
|---|---:|
| Hit@1 | 0.8889 |
| Hit@3 | 1.0000 |
| MRR | 0.9444 |
| evidence_coverage | 0.4074 |
| all_evidence_rate | 0.2963 |
| nDCG@10 | 0.9554 |

失败桶：`all_evidence=8`、`partial_evidence=6`、`node_hit_no_evidence=13`、
`negative=9`。

这组数字只说明 fixture 的行为稳定、指标能区分失败类型；**不能**当成真实
BGE/Chroma 或 RAGFlow 的检索质量。真实基线必须在 `--backend chroma` 与
`--backend ragflow` 上分别生成。

## 门禁

CI 只跑 fixture gate：确定性、无模型、无网络。真实 Chroma/RAGFlow 回归需要显式
环境，放在 manual/nightly；两者报告都记录 dataset/manifest hash、top_k、后端和
失败桶。任何默认检索/切片/索引改动都必须附 before/after。

## 限制

- 36 题是 agent 看过源文后写的，不是独立盲测；heldout 只是预留组。
- 检索层指标不等于回答正确率；引用合法/事实支持仍由生成层和人工复核负责。
- fixture 的 hit@3 高不代表真实检索好；它只是让 CI 能在没有模型时发现报告/指标
  代码回归。
- RAGFlow 真实报告尚未生成；Docker daemon/API Key 就绪后先用同一题集跑
  `--backend ragflow`，再与 Chroma 对比。