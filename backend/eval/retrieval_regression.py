"""检索质量回归：只评检索层，不调用生成模型。

指标固定为 Hit@1/3、MRR、gold 证据覆盖、整题证据齐全、nDCG@10 和延迟。
`fixture` 后端是确定性词项检索，只用于 CI plumbing；Chroma/RAGFlow 后端才代表
真实索引质量。
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from typing import Iterable

from eval.benchmark import BenchmarkCase, EvidenceTarget

MEASURED_METRICS = (
    'hit@1', 'hit@3', 'mrr', 'evidence_coverage', 'all_evidence_rate', 'ndcg@10',
)


def _compact(value: str | None) -> str:
    return re.sub(r'\s+', '', value or '')


def _target_present(content: str, target: EvidenceTarget) -> bool:
    text, head, tail = _compact(content), _compact(target.head), _compact(target.tail)
    start = text.find(head)
    return bool(head) and start >= 0 and (not tail or text.find(tail, start) >= 0)


def targets_of(case: BenchmarkCase) -> tuple[EvidenceTarget, ...]:
    if case.gold_evidence:
        return case.gold_evidence
    if case.gold_node_id is not None:
        return (EvidenceTarget(case.gold_node_id, case.evidence_head or '',
                               case.evidence_tail),)
    return ()


def ordered_node_ids(rows: Iterable[dict]) -> list[int]:
    return list(dict.fromkeys(
        row['node_id'] for row in rows
        if isinstance(row, dict) and type(row.get('node_id')) is int
    ))


def _coverage(case: BenchmarkCase, rows: list[dict]) -> tuple[int, int]:
    targets = targets_of(case)
    covered = 0
    for target in targets:
        if any(
            row.get('node_id') == target.node_id
            and isinstance(row.get('content'), str)
            and _target_present(row['content'], target)
            for row in rows
        ):
            covered += 1
    return covered, len(targets)


def _ndcg(case: BenchmarkCase, rows: list[dict], k: int = 10) -> float | None:
    gold = {target.node_id for target in targets_of(case)}
    if not gold:
        return None
    ranked = ordered_node_ids(rows)[:k]
    dcg = sum(1.0 / math.log2(index + 2) for index, node_id in enumerate(ranked)
              if node_id in gold)
    ideal = sum(1.0 / math.log2(index + 2) for index in range(min(len(gold), k)))
    return dcg / ideal if ideal else None


def evaluate_case(case: BenchmarkCase, rows: list[dict], *, latency_ms: float) -> dict:
    targets = targets_of(case)
    ids = ordered_node_ids(rows)
    gold = {target.node_id for target in targets}
    covered, total = _coverage(case, rows)
    first_gold_rank = next(
        (index + 1 for index, node_id in enumerate(ids) if node_id in gold), None,
    )
    if not targets:
        bucket = 'negative'
    elif first_gold_rank is None:
        bucket = 'not_retrieved'
    elif covered == 0:
        bucket = 'node_hit_no_evidence'
    elif covered < total:
        bucket = 'partial_evidence'
    else:
        bucket = 'all_evidence'
    return {
        'case_id': case.case_id,
        'gold_node_ids': sorted(gold),
        'retrieved_node_ids': ids,
        'hit@1': int(bool(gold) and bool(ids) and ids[0] in gold),
        'hit@3': int(bool(gold) and any(node_id in gold for node_id in ids[:3])),
        'mrr': None if first_gold_rank is None else 1.0 / first_gold_rank,
        'covered_targets': covered,
        'target_count': total,
        'evidence_coverage': None if total == 0 else covered / total,
        'all_evidence': None if total == 0 else int(covered == total),
        'ndcg@10': _ndcg(case, rows),
        'bucket': bucket,
        'latency_ms': latency_ms,
    }


def _mean(values: list[float]) -> float | None:
    return round(statistics.fmean(values), 6) if values else None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return round(ordered[0], 3)
    position = (len(ordered) - 1) * fraction
    low = math.floor(position)
    high = math.ceil(position)
    if low == high:
        return round(ordered[low], 3)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


def summarize(cases: list[BenchmarkCase], records: list[dict], *,
              case_metadata: dict[str, dict] | None = None) -> dict:
    positive = [record for record in records if record['target_count'] > 0]
    metrics = {
        'hit@1': _mean([record['hit@1'] for record in positive]),
        'hit@3': _mean([record['hit@3'] for record in positive]),
        'mrr': _mean([record['mrr'] for record in positive if record['mrr'] is not None]),
        'evidence_coverage': _mean([
            record['evidence_coverage'] for record in positive
            if record['evidence_coverage'] is not None
        ]),
        'all_evidence_rate': _mean([
            record['all_evidence'] for record in positive
            if record['all_evidence'] is not None
        ]),
        'ndcg@10': _mean([
            record['ndcg@10'] for record in positive if record['ndcg@10'] is not None
        ]),
    }
    latencies = [record['latency_ms'] for record in records]
    by_split = {}
    by_category = {}
    if case_metadata:
        grouped = defaultdict(list)
        for record in records:
            meta = case_metadata.get(record['case_id'], {})
            grouped[meta.get('split', 'unknown')].append(record)
            by_category.setdefault(meta.get('query_category', 'unknown'), []).append(record)
        by_split = {
            split: _positive_metrics(rows) for split, rows in grouped.items()
        }
        by_category = {
            category: _positive_metrics(rows) for category, rows in by_category.items()
        }
    return {
        'case_count': len(records),
        'positive_cases': len(positive),
        'negative_cases': len(records) - len(positive),
        'metrics': metrics,
        'latency_ms': {
            'p50': _percentile(latencies, 0.5),
            'p95': _percentile(latencies, 0.95),
        },
        'failure_buckets': dict(sorted(Counter(
            record['bucket'] for record in records
        ).items())),
        'by_split': by_split,
        'by_category': by_category,
    }


def _positive_metrics(records: list[dict]) -> dict:
    positive = [record for record in records if record['target_count'] > 0]
    return {
        'n': len(positive),
        'hit@3': _mean([record['hit@3'] for record in positive]),
        'evidence_coverage': _mean([
            record['evidence_coverage'] for record in positive
            if record['evidence_coverage'] is not None
        ]),
    }


def compare_metrics(baseline: dict, candidate: dict) -> dict:
    regressions = {}
    for metric in MEASURED_METRICS:
        old, new = baseline.get(metric), candidate.get(metric)
        if old is None or new is None:
            continue
        if new < old - 1e-9:
            regressions[metric] = {'baseline': old, 'candidate': new,
                                   'delta': round(new - old, 6)}
    return {'passed': not regressions, 'regressions': regressions}


# ---------------------------------------------------------------- fixture backend

def _terms(value: str) -> set[str]:
    ascii_terms = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', value.lower())
    chinese = re.findall(r'[\u4e00-\u9fff]+', value)
    return set(ascii_terms + [
        part[index:index + 2]
        for part in chinese
        for index in range(len(part) - 1)
    ])


def _fixture_chunks(content: str, *, size: int = 800) -> list[str]:
    pieces = []
    for paragraph in re.split(r'\n\s*\n', content):
        paragraph = paragraph.strip()
        for offset in range(0, len(paragraph), size):
            piece = paragraph[offset:offset + size].strip()
            if piece:
                pieces.append(piece)
    return pieces


def fixture_retrieve(corpus: dict[int, str], query: str, *, top_k: int) -> list[dict]:
    """确定性词项检索；只用于 CI/报告 schema，不代表真实 embedding 质量。"""
    if top_k < 1:
        raise ValueError('top_k must be positive')
    query_terms = _terms(query)
    per_node: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for node_id, content in corpus.items():
        for index, chunk in enumerate(_fixture_chunks(content)):
            score = len(query_terms & _terms(chunk))
            if score:
                per_node[node_id].append((score, index, chunk))
    ranked_nodes = sorted(
        per_node,
        key=lambda node_id: (-max(item[0] for item in per_node[node_id]), node_id),
    )[:top_k]
    rows = []
    for node_id in ranked_nodes:
        for score, index, chunk in sorted(
            per_node[node_id], key=lambda item: (-item[0], item[1]),
        )[:2]:
            rows.append({
                'node_id': node_id,
                'content': chunk,
                'distance': None,
                'fixture_score': score,
                'chunk_index': index,
            })
    return rows


def summarize_fixture(cases: list[BenchmarkCase], corpus: dict[int, str], *,
                      top_k: int, case_metadata: dict[str, dict] | None = None) -> dict:
    import time

    records = []
    for case in cases:
        started = time.perf_counter()
        rows = fixture_retrieve(corpus, case.question, top_k=top_k)
        latency = (time.perf_counter() - started) * 1000
        records.append(evaluate_case(case, rows, latency_ms=latency))
    return summarize(cases, records, case_metadata=case_metadata)