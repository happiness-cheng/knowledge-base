"""检索回归指标、fixture 确定性、CLI 报告与 gate。"""

import json

import pytest

from eval.benchmark import BenchmarkCase, EvidenceTarget
from eval.retrieval_regression import (
    compare_metrics,
    evaluate_case,
    fixture_retrieve,
    summarize,
)


def make_case(case_id="C1", targets=None):
    if targets is None:
        targets = (EvidenceTarget(1, "开始", "结束"),)
    return BenchmarkCase(case_id, "问题", gold_evidence=targets)


def test_perfect_case_metrics():
    case = make_case()
    record = evaluate_case(
        case, [{"node_id": 1, "content": "开始 中间 结束"}], latency_ms=12.0,
    )
    assert record["hit@1"] == 1
    assert record["hit@3"] == 1
    assert record["mrr"] == 1.0
    assert record["evidence_coverage"] == 1.0
    assert record["all_evidence"] == 1
    assert record["ndcg@10"] == 1.0
    assert record["bucket"] == "all_evidence"


def test_missing_node_and_node_hit_without_evidence_are_distinguished():
    case = make_case()
    missed = evaluate_case(case, [{"node_id": 2, "content": "无关"}], latency_ms=1)
    assert missed["bucket"] == "not_retrieved"
    assert missed["mrr"] is None

    node_only = evaluate_case(case, [{"node_id": 1, "content": "没有锚点"}], latency_ms=1)
    assert node_only["bucket"] == "node_hit_no_evidence"
    assert node_only["hit@1"] == 1
    assert node_only["evidence_coverage"] == 0.0


def test_partial_evidence_and_aggregate_by_split():
    case = make_case(targets=(
        EvidenceTarget(1, "A", None), EvidenceTarget(2, "B", None),
    ))
    record = evaluate_case(
        case, [{"node_id": 1, "content": "A"}], latency_ms=5,
    )
    assert record["covered_targets"] == 1
    assert record["evidence_coverage"] == 0.5
    assert record["all_evidence"] == 0
    assert record["bucket"] == "partial_evidence"

    summary = summarize(
        [case], [record],
        case_metadata={"C1": {"split": "development", "query_category": "semantic_rephrase"}},
    )
    assert summary["positive_cases"] == 1
    assert summary["metrics"]["evidence_coverage"] == 0.5
    assert summary["by_split"]["development"]["n"] == 1
    assert summary["by_category"]["semantic_rephrase"]["hit@3"] == 1


def test_fixture_is_deterministic_and_respects_top_k():
    corpus = {
        1: "alpha beta gamma\n\nsecond alpha paragraph",
        2: "beta only",
        3: "gamma only",
    }
    first = fixture_retrieve(corpus, "alpha", top_k=2)
    second = fixture_retrieve(corpus, "alpha", top_k=2)
    assert first == second
    assert {row["node_id"] for row in first} == {1}
    assert len(first) <= 2


def test_compare_metrics_detects_regression():
    baseline = {"hit@3": 1.0, "evidence_coverage": 1.0, "mrr": 1.0}
    same = compare_metrics(baseline, {"hit@3": 1.0, "evidence_coverage": 1.0, "mrr": 1.0})
    assert same["passed"] is True
    worse = compare_metrics(baseline, {"hit@3": 1.0, "evidence_coverage": 0.8, "mrr": 1.0})
    assert worse["passed"] is False
    assert worse["regressions"]["evidence_coverage"]["delta"] == pytest.approx(-0.2)


def test_cli_frozen_dense_reads_tracked_report(tmp_path):
    from eval.run_retrieval_regression import DEFAULT_FROZEN, main

    assert DEFAULT_FROZEN.is_file()
    output = tmp_path / "frozen.json"
    assert main(["--backend", "frozen-dense", "--limit", "2",
                 "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["backend"] == "frozen-dense"
    assert report["retrieval_quality_measured"] is True
    assert report["frozen_report_sha256"]


def test_cli_writes_report_and_gate_passes(tmp_path):
    from eval.run_retrieval_regression import main

    report = tmp_path / "fixture.json"
    baseline = tmp_path / "fixture-baseline.json"
    assert main(["--backend", "fixture", "--limit", "3",
                 "--output", str(report), "--write-baseline", str(baseline)]) == 0
    assert json.loads(report.read_text(encoding="utf-8"))["backend"] == "fixture"
    assert json.loads(baseline.read_text(encoding="utf-8"))["backend"] == "fixture"

    second = tmp_path / "fixture-2.json"
    assert main(["--backend", "fixture", "--limit", "3",
                 "--output", str(second), "--baseline", str(baseline),
                 "--gate"]) == 0