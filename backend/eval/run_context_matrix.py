"""复用已验证 K3 排名，离线比较真实 token 预算与相邻块，不重跑模型。"""

import argparse
import json
import os
import socket
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from eval.benchmark import file_hash, render_markdown
from eval.context_candidates import expand_neighbors
from eval.core_corpus import load_manifest_corpus, validate_core_dataset
from eval.retrieval_candidates import (
    CandidateChunk,
    ChunkConfig,
    RankedChunk,
    chunk_documents,
)
from eval.run_retrieval_matrix import _observation, _report, _snapshot


def main(argv=None):
    backend = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, default=backend / 'eval/reports/retrieval-matrix/20261014T044942416805Z')
    parser.add_argument('--hf-home', type=Path, default=Path('D:/AI_Models/huggingface'))
    parser.add_argument('--output', type=Path, default=backend / 'eval/reports/context-matrix')
    args = parser.parse_args(argv)

    def no_network(*unused_args, **unused_kwargs):
        raise RuntimeError('external network disabled for context matrix')

    with patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network), patch.dict(os.environ, {
        'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'ANONYMIZED_TELEMETRY': 'False',
    }):
        from transformers import AutoTokenizer
        source = json.loads((args.baseline / 'k3-rrf.json').read_text(encoding='utf-8'))
        manifest_path = backend / 'eval/fixtures/core-rag-corpus-20261013.json'
        dataset_path = backend / 'eval/fixtures/core-rag-20261013.json'
        if source['metadata']['dataset_hash'] != file_hash(dataset_path) or source['metadata']['corpus_manifest_hash'] != file_hash(manifest_path):
            raise ValueError('frozen source hashes differ from measured K3')
        corpus = load_manifest_corpus(manifest_path, backend.parent)
        cases = validate_core_dataset(dataset_path, corpus)
        details = json.loads(dataset_path.read_text(encoding='utf-8'))['case_metadata']
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        frozen_chunks = json.loads((args.baseline / 'chunk-manifest.json').read_text(encoding='utf-8'))
        snapshot, revision = _snapshot(args.hf_home, 'BAAI/bge-large-zh-v1.5')
        if revision != source['metadata']['embedding_revision']:
            raise ValueError('tokenizer revision differs from measured K3')
        tokenizer = AutoTokenizer.from_pretrained(snapshot, local_files_only=True)
        rebuilt = chunk_documents([{**document, 'user_id': 1, 'content': corpus[document['node_id']]}
            for document in manifest['documents']], tokenizer, ChunkConfig(**frozen_chunks['config']))
        if [asdict(chunk) for chunk in rebuilt] != frozen_chunks['chunks']:
            raise ValueError('source-order chunk snapshot differs from measured K3')
        chunks = [CandidateChunk(**row) for row in frozen_chunks['chunks']]
        by_id = {chunk.chunk_id: chunk for chunk in chunks}
        source_rows = {row['case_id']: row for row in source['cases']}
        if set(source_rows) != {case.case_id for case in cases}:
            raise ValueError('case set differs from measured K3')
        output = args.output / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
        output.mkdir(parents=True, exist_ok=False)
        reports = {}
        for budget in (1024, 1536, 2048):
            for neighbors in (False, True):
                name = f'rrf_{budget}_neighbors_{int(neighbors)}'
                observations = {}
                for case in cases:
                    row = source_rows[case.case_id]
                    if row['question'] != case.question:
                        raise ValueError('question differs from measured K3')
                    pool = next(step for step in row['steps'] if step.get('stage') == 'candidate_pool')
                    ranked = [RankedChunk(by_id[identity], 0, 'rrf') for identity in pool['chunk_ids']]
                    expanded, trace = expand_neighbors(ranked, chunks, user_id=1, enabled=neighbors)
                    observations[case.case_id] = _observation(case, expanded, tokenizer, budget,
                        extra_steps=[{'stage': 'adjacent_context', **trace}])
                    if (budget == 1536 and not neighbors
                            and [item['chunk_id'] for item in observations[case.case_id].retrieved]
                            != [item['chunk_id'] for item in row['retrieved']]):
                        raise ValueError('same-budget control differs from baseline')
                report = _report(cases, corpus, observations, {
                    'variant': name, 'llm_called': False, 'neighbors': neighbors,
                    'context_budget_bge_tokens': budget, 'baseline_report_sha256': file_hash(args.baseline / 'k3-rrf.json'),
                    'dataset_hash': file_hash(dataset_path), 'corpus_manifest_hash': file_hash(manifest_path),
                    'latency_basis': 'context packing only; no embedding/reranker/model generation',
                    'code_hashes': {path: file_hash(backend / path) for path in ('eval/context_candidates.py', 'eval/run_context_matrix.py')},
                }, details)
                (output / f'{name}.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                (output / f'{name}.md').write_text(render_markdown(report), encoding='utf-8')
                reports[name] = {'summary': report['summary'], 'splits': report['splits']}
        # 只按开发集选择；同分优先更小预算和不扩展。预留集只报告。
        winner = max(reports, key=lambda name: (
            reports[name]['splits']['development']['evidence_all_covered'],
            reports[name]['splits']['development']['evidence_coverage'],
            -int(name.split('_')[1]), -int(name[-1])))
        summary = {'variants': reports, 'development_selected': winner,
                   'applied_to_production': False, 'source_aware_not_blind': True,
                   'production_limit': 'index needs durable source-order metadata before neighbor integration'}
        (output / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'output': str(output), 'development_selected': winner, 'llm_called': False}, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
