"""检索质量回归 CLI：fixture（CI）/ chroma / ragflow 三种后端。

fixture 不加载模型或网络，用于验证指标与报告 schema；真实质量必须用 chroma
或 ragflow，并记录 dataset/manifest hash、top_k 和后端。
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from eval.benchmark import file_hash
from eval.core_corpus import load_manifest_corpus, validate_core_dataset
from eval.retrieval_regression import (
    compare_metrics,
    evaluate_case,
    fixture_retrieve,
    summarize,
)

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
DEFAULT_MANIFEST = BACKEND / 'eval/fixtures/core-rag-corpus-20261013.json'
DEFAULT_DATASET = BACKEND / 'eval/fixtures/core-rag-20261013.json'
DEFAULT_FROZEN = (BACKEND / 'eval/reports/retrieval-matrix/'
                  '20261014T044942416805Z/k3-dense.json')


def _load_inputs(manifest_path: Path, dataset_path: Path):
    corpus = load_manifest_corpus(manifest_path, REPO_ROOT)
    cases = validate_core_dataset(dataset_path, corpus)
    raw = json.loads(dataset_path.read_text(encoding='utf-8'))
    metadata = raw.get('case_metadata', {})
    return corpus, cases, metadata


def _retrieve(backend: str, *, corpus, query: str, top_k: int, user_id: int,
              case_id: str = '', frozen: dict[str, list[dict]] | None = None) -> list[dict]:
    if backend == 'fixture':
        return fixture_retrieve(corpus, query, top_k=top_k)
    if backend == 'frozen-dense':
        if frozen is None or case_id not in frozen:
            raise ValueError(f'frozen report has no case {case_id}')
        return frozen[case_id]
    if backend == 'chroma':
        from app.services.rag_service import retrieve_relevant_nodes

        return retrieve_relevant_nodes(query, top_k=top_k, user_id=user_id)
    if backend == 'ragflow':
        from app.database import SessionLocal
        from app.services.ragflow_client import get_ragflow_client
        from app.services.ragflow_retrieval import retrieve_for_user

        client = get_ragflow_client()
        if client is None:
            raise RuntimeError('RAGFlow backend selected but RAGFLOW_BASE_URL/API_KEY missing')
        with SessionLocal() as db:
            return retrieve_for_user(
                db, user_id=user_id, query=query, top_k=top_k, client=client,
            )
    raise ValueError(f'unknown backend: {backend}')


def _render_markdown(report: dict) -> str:
    metrics = report['summary']['metrics']
    lines = [
        f"# Retrieval regression — {report['backend']}",
        '',
        f"- generated_at: {report['generated_at']}",
        f"- dataset_sha256: `{report['dataset_sha256']}`",
        f"- manifest_sha256: `{report['manifest_sha256']}`",
        f"- top_k: {report['top_k']}",
        f"- retrieval_quality_measured: {report['retrieval_quality_measured']}",
        '',
        '| metric | value |',
        '|---|---:|',
    ]
    for key in ('hit@1', 'hit@3', 'mrr', 'evidence_coverage',
                'all_evidence_rate', 'ndcg@10'):
        value = metrics.get(key)
        lines.append(f'| {key} | {"—" if value is None else f"{value:.4f}"} |')
    lines.extend([
        '',
        f"- positive_cases: {report['summary']['positive_cases']}",
        f"- negative_cases: {report['summary']['negative_cases']}",
        f"- p50_ms: {report['summary']['latency_ms']['p50']}",
        f"- p95_ms: {report['summary']['latency_ms']['p95']}",
        '',
        '## Failure buckets',
        '',
    ])
    for bucket, count in report['summary']['failure_buckets'].items():
        lines.append(f'- {bucket}: {count}')
    lines.extend(['', '## Per split', '', '| split | n | hit@3 | evidence_coverage |', '|---|---:|---:|---:|'])
    for split, values in report['summary']['by_split'].items():
        hit = '—' if values['hit@3'] is None else f"{values['hit@3']:.4f}"
        cov = '—' if values['evidence_coverage'] is None else f"{values['evidence_coverage']:.4f}"
        lines.append(f"| {split} | {values['n']} | {hit} | {cov} |")
    return '\n'.join(lines) + '\n'


def _new_output_dir() -> Path:
    stamp = datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    return BACKEND / 'eval/reports/retrieval-regression' / stamp


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('fixture', 'frozen-dense', 'chroma', 'ragflow'), required=True)
    parser.add_argument('--frozen-report', type=Path, default=DEFAULT_FROZEN,
                        help='frozen-dense 读取的 k3-dense.json')
    parser.add_argument('--manifest', type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument('--dataset', type=Path, default=DEFAULT_DATASET)
    parser.add_argument('--top-k', type=int, default=3)
    parser.add_argument('--user-id', type=int, default=1)
    parser.add_argument('--limit', type=int, default=0, help='只跑前 N 条（调试）')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--gate', action='store_true', help='有回归时退出码 2')
    parser.add_argument('--write-baseline', type=Path)
    args = parser.parse_args(argv)
    if args.top_k < 1:
        parser.error('--top-k must be positive')
    if args.gate and args.baseline is None:
        parser.error('--gate requires --baseline')

    corpus, cases, metadata = _load_inputs(args.manifest, args.dataset)
    if args.limit:
        cases = cases[:args.limit]
    frozen = None
    if args.backend == 'frozen-dense':
        raw = json.loads(args.frozen_report.read_text(encoding='utf-8'))
        frozen = {
            row['case_id']: row.get('retrieved', [])
            for row in raw.get('cases', []) if isinstance(row, dict) and row.get('case_id')
        }
    records = []
    for case in cases:
        started = time.perf_counter()
        rows = _retrieve(args.backend, corpus=corpus, query=case.question,
                         top_k=args.top_k, user_id=args.user_id,
                         case_id=case.case_id, frozen=frozen)
        latency = (time.perf_counter() - started) * 1000
        records.append(evaluate_case(case, rows, latency_ms=latency))
    summary = summarize(cases, records, case_metadata=metadata)
    report = {
        'schema_version': 1,
        'generated_at': datetime.now(UTC).isoformat(),
        'backend': args.backend,
        'top_k': args.top_k,
        'dataset_sha256': file_hash(args.dataset),
        'manifest_sha256': file_hash(args.manifest),
        'retrieval_quality_measured': args.backend != 'fixture',
        'model_quality_measured': False,
        'frozen_report': str(args.frozen_report) if args.backend == 'frozen-dense' else None,
        'frozen_report_sha256': file_hash(args.frozen_report)
        if args.backend == 'frozen-dense' else None,
        'note': (
            'fixture 是确定性词项检索，仅验证指标/report；不代表真实 embedding 质量'
            if args.backend == 'fixture' else
            'frozen-dense 使用已冻结的 k3-dense 报告（真实 BGE 向量、精确内积、20 候选）；'
            '不是当前在线索引'
            if args.backend == 'frozen-dense' else
            '检索层指标；未评估生成答案质量'
        ),
        'summary': summary,
        'cases': records,
    }

    output = args.output or (_new_output_dir() / 'summary.json')
    if output.exists():
        parser.error(f'refusing to overwrite existing report: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    output.with_suffix('.md').write_text(_render_markdown(report), encoding='utf-8')
    print(json.dumps({'backend': args.backend, 'report': str(output),
                      'metrics': summary['metrics'],
                      'buckets': summary['failure_buckets']}, ensure_ascii=False))

    if args.write_baseline:
        baseline = {
            'schema_version': 1,
            'backend': args.backend,
            'top_k': args.top_k,
            'dataset_sha256': report['dataset_sha256'],
            'manifest_sha256': report['manifest_sha256'],
            'metrics': summary['metrics'],
        }
        if args.write_baseline.exists():
            parser.error(f'refusing to overwrite baseline: {args.write_baseline}')
        args.write_baseline.parent.mkdir(parents=True, exist_ok=True)
        args.write_baseline.write_text(
            json.dumps(baseline, ensure_ascii=False, indent=2) + '\n', encoding='utf-8',
        )

    if args.baseline:
        baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
        if baseline.get('dataset_sha256') != report['dataset_sha256']:
            print(json.dumps({'status': 'dataset_mismatch'}, ensure_ascii=False))
            return 2
        if baseline.get('backend') != args.backend:
            print(json.dumps({'status': 'backend_mismatch',
                              'baseline': baseline.get('backend'),
                              'candidate': args.backend}, ensure_ascii=False))
            return 2
        comparison = compare_metrics(baseline.get('metrics', {}), summary['metrics'])
        print(json.dumps({'gate': comparison}, ensure_ascii=False))
        if not comparison['passed']:
            return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())