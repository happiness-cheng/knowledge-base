"""已缓存模型的本地检索矩阵：禁止网络，不加载应用配置或数据库。"""

import argparse
import gc
import importlib.metadata
import json
import os
import re
import socket
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from unittest.mock import patch

from eval.benchmark import BenchmarkObservation, evaluate, file_hash, render_markdown
from eval.core_corpus import load_manifest_corpus, validate_core_dataset
from eval.retrieval_candidates import (
    BM25Retriever,
    CandidateChunk,
    ChunkConfig,
    RankedChunk,
    chunk_documents,
    dense_rank,
    pack_context,
    reciprocal_rank_fusion,
    rerank_candidates,
)


def oracle_chunk_report(cases, chunks, case_metadata):
    rows = []
    for case in cases:
        covered = 0
        for target in case.gold_evidence:
            head = re.sub(r'\s+', '', target.head)
            tail = re.sub(r'\s+', '', target.tail or '')
            for chunk in chunks:
                if chunk.node_id != target.node_id:
                    continue
                text = re.sub(r'\s+', '', chunk.content)
                start = text.find(head)
                if start >= 0 and (not tail or text.find(tail, start) >= 0):
                    covered += 1
                    break
        total = len(case.gold_evidence)
        rows.append({'case_id': case.case_id, 'split': case_metadata[case.case_id]['split'],
                     'evidence_covered': covered, 'evidence_targets': total,
                     'all_covered': int(bool(total) and covered == total)})
    return rows


def select_chunk_config(reports):
    def score(report):
        rows = [row for row in report['cases'] if row['split'] == 'development' and row['evidence_targets']]
        total = sum(row['evidence_targets'] for row in rows)
        return (sum(row['all_covered'] for row in rows),
                sum(row['evidence_covered'] for row in rows) / total if total else 0,
                -report['chunk_count'], int(report['config']['strategy'] == 'heading'))
    return max(reports, key=score)['config']


def select_rrf_k(development_summaries):
    def score(key):
        summary = development_summaries[key]
        return (summary.get('evidence_all_covered') or 0,
                summary.get('evidence_coverage') or 0,
                summary.get('document_recall_at_3') or 0, -abs(key - 60))
    return max(development_summaries, key=score)


def _save(path, document):
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _snapshot(hf_home, repo_id):
    cache = hf_home / 'hub' / ('models--' + repo_id.replace('/', '--'))
    revision = (cache / 'refs/main').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('invalid cached model revision')
    snapshot = cache / 'snapshots' / revision
    if not snapshot.is_dir():
        raise ValueError('cached model snapshot missing; downloads forbidden')
    return snapshot, revision


def _report(cases, corpus, observations, metadata, case_metadata):
    report = evaluate(cases, corpus, lambda case: observations[case.case_id], metadata)
    report['splits'] = {}
    for split in ('development', 'heldout'):
        subset = [case for case in cases if case_metadata[case.case_id]['split'] == split]
        report['splits'][split] = evaluate(subset, corpus, lambda case: observations[case.case_id], metadata)['summary']
    for row in report['cases']:
        row['dataset_metadata'] = case_metadata[row['case_id']]
    return report


def _observation(case, ranked, tokenizer, budget, *, encoding_ms=0., prediction_ms=0., extra_steps=()):
    started = perf_counter()
    context, packing = pack_context(ranked, tokenizer, user_id=1, token_budget=budget)
    warm_ms = (perf_counter() - started) * 1000
    pool_ids = list(dict.fromkeys(item.chunk.node_id for item in ranked))
    gold_ids = {target.node_id for target in case.gold_evidence}
    candidate = {'stage': 'candidate_pool', 'chunk_ids': [item.chunk.chunk_id for item in ranked],
                 'node_ids': pool_ids, 'candidate_count': len(ranked),
                 'document_recall_at_1': len(gold_ids & set(pool_ids[:1])) / len(gold_ids) if gold_ids else None,
                 'document_recall_at_3': len(gold_ids & set(pool_ids[:3])) / len(gold_ids) if gold_ids else None}
    timing = {'stage': 'timing', 'uncached_query_encoding_ms': encoding_ms,
              'shared_20_pair_prediction_ms': prediction_ms, 'context_pack_ms': warm_ms}
    return BenchmarkObservation(
        retrieved=[{'node_id': item.chunk.node_id, 'chunk_id': item.chunk.chunk_id,
                    'title': item.chunk.title, 'heading': item.chunk.heading, 'content': item.chunk.content,
                    'score': item.score, 'source': item.source, 'token_count': item.chunk.token_count}
                   for item in context],
        latency_ms=encoding_ms + prediction_ms + warm_ms,
        steps=[candidate, {'stage': 'packed_context', **packing}, timing, *extra_steps])


def write_disabled_pool_reports(*, output, metadata, cases, corpus, details, tokenizer,
                                fused_pools, query_encoding_ms, context_budget):
    """对每个候选数保存关闭精排的匹配控制，避免混淆pool变化与精排效果。"""
    reports = {}
    for size in (5, 10, 20):
        name = f'rrf_off_{size}'
        observations = {case.case_id: _observation(case, fused_pools[case.case_id][:size], tokenizer,
            context_budget, encoding_ms=query_encoding_ms[case.case_id],
            extra_steps=[{'stage': 'reranker', 'status': 'disabled', 'pool_size': size, 'pairs': 0}])
            for case in cases}
        report = _report(cases, corpus, observations, {**metadata, 'variant': name,
            'reranker_pool': size, 'reranker_enabled': False,
            'control_postprocess_code_hash': file_hash(Path(__file__))}, details)
        _save(output / f'k4-{name}.json', report)
        (output / f'k4-{name}.md').write_text(render_markdown(report), encoding='utf-8')
        reports[name] = report
    _save(output / 'matched-disabled-summary.json', {name: {'summary': report['summary'], 'splits': report['splits']}
                                                    for name, report in reports.items()})
    return reports


def run(args):
    if getattr(args, 'resume_k3', None):
        return resume_k3(args)
    os.environ.update(HF_HOME=str(args.hf_home), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', ANONYMIZED_TELEMETRY='False')
    backend = Path(__file__).resolve().parents[1]
    dataset = json.loads(args.dataset.read_text(encoding='utf-8'))
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if dataset['metadata']['corpus_manifest_sha256'] != file_hash(args.manifest):
        raise ValueError('dataset manifest hash mismatch')
    corpus = load_manifest_corpus(args.manifest, backend.parent)
    cases = validate_core_dataset(args.dataset, corpus)
    details = dataset['case_metadata']
    documents = [{'node_id': row['node_id'], 'user_id': 1, 'title': row['title'],
                  'content': corpus[row['node_id']]} for row in manifest['documents']]
    output = args.output / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=False)
    metadata = {'mode': 'retrieval', 'frozen_at': dataset['metadata']['frozen_at'],
        'measured_at_utc': datetime.now(UTC).isoformat(), 'dataset_hash': file_hash(args.dataset),
        'corpus_manifest_hash': file_hash(args.manifest), 'device': args.device, 'threads': args.threads,
        'llm_called': False, 'model_quality_measured': False, 'retrieval_quality_measured': True,
        'network': 'socket connections blocked; cached snapshots only',
        'context_budget_bge_tokens': args.context_budget, 'user_id': 1,
        'evaluation_stage': 'packed_context; candidate-pool Recall retained separately in steps',
        'latency_basis': 'query encoding + context packing + shared real20-pair inference when reranked; excludes load/index; pool5/10 cache time is not inference',
        'code_hashes': {name: file_hash(backend / name) for name in (
            'eval/benchmark.py', 'eval/core_corpus.py', 'eval/retrieval_candidates.py',
            'eval/run_retrieval_matrix.py', 'app/utils/markdown_cleaner.py')}}
    def announce(stage, **values):
        print(json.dumps({'stage': stage, 'output': str(output), **values}, ensure_ascii=False), flush=True)
    announce('start', cases=len(cases), source_documents=len(documents))
    import torch
    from sentence_transformers import SentenceTransformer
    from transformers import AutoTokenizer

    torch.set_num_threads(args.threads)
    metadata['runtime_versions'] = {name: importlib.metadata.version(name) for name in (
        'torch', 'sentence-transformers', 'transformers', 'numpy', 'rank-bm25', 'jieba')}
    embedding_path, embedding_revision = _snapshot(args.hf_home, 'BAAI/bge-large-zh-v1.5')
    _, reranker_revision = _snapshot(args.hf_home, 'BAAI/bge-reranker-v2-m3')
    metadata.update(embedding_revision=embedding_revision, reranker_revision=reranker_revision)
    tokenizer = AutoTokenizer.from_pretrained(str(embedding_path), local_files_only=True, use_fast=True)
    tokenizer.model_max_length = 10 ** 9  # 原文计数不截断；完整块输入另行强制512。
    oracle_reports = []
    started = perf_counter()
    for strategy in ('fixed', 'heading'):
        for body_tokens in (256, 384, 480):
            for overlap in (0, 32):
                config = ChunkConfig(strategy, body_tokens, overlap, 512)
                chunks = chunk_documents(documents, tokenizer, config)
                oracle_reports.append({'config': asdict(config), 'chunk_count': len(chunks),
                    'max_full_input_tokens': max(chunk.token_count for chunk in chunks),
                    'cases': oracle_chunk_report(cases, chunks, details)})
    selected = select_chunk_config(oracle_reports)
    _save(output / 'k1-oracle.json', {'metadata': metadata, 'status': 'partial_K1_oracle_only',
        'selection_rule': 'development all-covered, coverage, fewer chunks; heldout never selects',
        'selected_config': selected, 'schemes': oracle_reports,
        'elapsed_ms': (perf_counter() - started) * 1000,
        'not_measured': '12 schemes have no complete embedding/retrieval A/B; oracle is not Recall'})
    announce('oracle_complete', selected_config=selected, schemes=len(oracle_reports))
    chunks = chunk_documents(documents, tokenizer, ChunkConfig(**selected))
    _save(output / 'chunk-manifest.json', {'config': selected, 'chunks': [asdict(chunk) for chunk in chunks]})
    started = perf_counter()
    embedding = SentenceTransformer(str(embedding_path), device=args.device, local_files_only=True)
    metadata['embedding_load_ms'] = (perf_counter() - started) * 1000
    assert embedding.get_sentence_embedding_dimension() == 1024
    assert embedding.max_seq_length == 512
    started = perf_counter()
    vectors = embedding.encode([chunk.embedding_text for chunk in chunks], normalize_embeddings=True,
                               batch_size=args.embedding_batch_size, show_progress_bar=True)
    metadata['chunk_embedding_ms'] = (perf_counter() - started) * 1000
    announce('chunk_embedding_complete', chunks=len(chunks), elapsed_ms=metadata['chunk_embedding_ms'])
    query_vectors, query_encoding_ms = {}, {}
    prefix = '为这个句子生成表示以用于检索相关文章：'
    for index, case in enumerate(cases, 1):
        started = perf_counter()
        full_query = prefix + case.question
        if len(tokenizer(full_query, add_special_tokens=True)['input_ids']) > 512:
            raise ValueError('query exceeds embedding token limit')
        query_vectors[case.case_id] = embedding.encode(full_query, normalize_embeddings=True, show_progress_bar=False)
        query_encoding_ms[case.case_id] = (perf_counter() - started) * 1000
        if index % 6 == 0:
            announce('query_embedding_progress', completed=index)
    del embedding
    gc.collect()
    started = perf_counter()
    bm25 = BM25Retriever(chunks, user_id=1)
    metadata['bm25_build_ms'] = (perf_counter() - started) * 1000
    dense_pools = {case.case_id: dense_rank(query_vectors[case.case_id], chunks, vectors, user_id=1, limit=20)
                   for case in cases}
    sparse_pools = {case.case_id: bm25.rank(case.question, 20) for case in cases}
    development = [case for case in cases if details[case.case_id]['split'] == 'development']
    tuning = {}
    for k in (20, 60, 120):
        observations = {case.case_id: _observation(case, reciprocal_rank_fusion(
            [dense_pools[case.case_id], sparse_pools[case.case_id]], user_id=1, k=k, limit=20),
            tokenizer, args.context_budget) for case in development}
        tuning[k] = evaluate(development, corpus, lambda case, observed=observations: observed[case.case_id], metadata)['summary']
    selected_k = select_rrf_k(tuning)
    metadata.update(chunk_config=selected, chunk_count=len(chunks), rrf_k=selected_k,
                    rrf_tuning_development_only=tuning, query_prefix=prefix,
                    embedding_normalized=True, candidate_pool=20)
    fused_pools = {case.case_id: reciprocal_rank_fusion(
        [dense_pools[case.case_id], sparse_pools[case.case_id]], user_id=1, k=selected_k, limit=20)
        for case in cases}
    all_reports = {}
    for name, pools in (('dense', dense_pools), ('bm25', sparse_pools), ('rrf', fused_pools)):
        observations = {case.case_id: _observation(case, pools[case.case_id], tokenizer, args.context_budget,
            encoding_ms=query_encoding_ms[case.case_id] if name != 'bm25' else 0.) for case in cases}
        report = _report(cases, corpus, observations, {**metadata, 'variant': name}, details)
        _save(output / f'k3-{name}.json', report)
        (output / f'k3-{name}.md').write_text(render_markdown(report), encoding='utf-8')
        all_reports[name] = report
        announce('k3_complete', variant=name, summary=report['summary'])
    _save(output / 'run-metadata.json', metadata)
    return _run_reranker(args, output=output, metadata=metadata, cases=cases, corpus=corpus,
                         details=details, tokenizer=tokenizer, fused_pools=fused_pools,
                         query_encoding_ms=query_encoding_ms, all_reports=all_reports)


def _run_reranker(args, *, output, metadata, cases, corpus, details, tokenizer,
                  fused_pools, query_encoding_ms, all_reports):
    import torch
    from sentence_transformers import CrossEncoder

    reranker_path, _ = _snapshot(args.hf_home, 'BAAI/bge-reranker-v2-m3')
    def announce(stage, **values):
        print(json.dumps({'stage': stage, 'output': str(output), **values}, ensure_ascii=False), flush=True)
    all_reports.update(write_disabled_pool_reports(output=output, metadata=metadata,
        cases=cases, corpus=corpus, details=details, tokenizer=tokenizer,
        fused_pools=fused_pools, query_encoding_ms=query_encoding_ms, context_budget=args.context_budget))
    started = perf_counter()
    reranker = CrossEncoder(str(reranker_path), device=args.device, max_length=512, local_files_only=True)
    metadata['reranker_load_ms'] = (perf_counter() - started) * 1000
    metadata['reranker_max_seq_length'] = reranker.max_seq_length
    metadata['actual_reranker_device'] = str(getattr(reranker, 'device', args.device))
    metadata['actual_torch_threads'] = torch.get_num_threads()
    predictions, traces, prediction_ms = {}, {}, {}
    for index, case in enumerate(cases, 1):
        started = perf_counter()
        result, trace = rerank_candidates(case.question, fused_pools[case.case_id],
            lambda pairs: reranker.predict(pairs, batch_size=args.rerank_batch_size, show_progress_bar=False),
            user_id=1, pool_size=20, tokenizer=reranker.tokenizer, max_length=512)
        prediction_ms[case.case_id] = (perf_counter() - started) * 1000
        predictions[case.case_id], traces[case.case_id] = result, trace
        _save(output / 'k4-score-checkpoint.json', {'metadata': metadata, 'completed': index, 'total': len(cases),
            'cases': {cid: {'scores': {item.chunk.chunk_id: item.score for item in scores},
                            'trace': traces[cid], 'real_20_pair_prediction_ms': prediction_ms[cid]}
                      for cid, scores in predictions.items()}})
        announce('reranker_progress', completed=index, total=len(cases), prediction_ms=prediction_ms[case.case_id], trace=trace)
    metadata['reranker_cold_first_batch_ms'] = prediction_ms[cases[0].case_id]
    for pool_size in (5, 10, 20):
        observations = {}
        for case in cases:
            started = perf_counter()
            base = fused_pools[case.case_id][:pool_size]
            allowed = {item.chunk.chunk_id for item in base}
            reranked = ([item for item in predictions[case.case_id] if item.chunk.chunk_id in allowed]
                        if traces[case.case_id]['status'] == 'ok' else base)
            trace = {**traces[case.case_id], 'stage': 'reranker', 'pool_size': pool_size,
                     'shared_real_pool_size': 20, 'cache_filter_sort_ms': (perf_counter() - started) * 1000,
                     'real_prediction_ms': prediction_ms[case.case_id],
                     'pair_truncation_scope': 'shared20 pool, not inferred per-subpool'}
            observations[case.case_id] = _observation(case, reranked, tokenizer, args.context_budget,
                encoding_ms=query_encoding_ms[case.case_id], prediction_ms=prediction_ms[case.case_id], extra_steps=[trace])
        name = f'rrf_reranker_{pool_size}'
        report = _report(cases, corpus, observations, {**metadata, 'variant': name,
            'reranker_pool': pool_size, 'reranker_score_cache': 'one real20-pair batch per query shared by5/10/20'}, details)
        report['reranker_degradations'] = sum(trace['status'] == 'degraded' for trace in traces.values())
        _save(output / f'k4-{name}.json', report)
        (output / f'k4-{name}.md').write_text(render_markdown(report), encoding='utf-8')
        all_reports[name] = report
        announce('k4_complete', variant=name, summary=report['summary'])
    _save(output / 'matrix-summary.json', {'metadata': metadata, 'output': str(output), 'K1': 'partial oracle only',
        'variants': {name: {'summary': report['summary'], 'splits': report['splits']}
                     for name, report in all_reports.items()},
        'limitations': ['source-aware authored36 cases, not an independent blind test',
                        'no LLM answers, refusal, generation tokens or cost benefits measured',
                        '5/10/20 share real20-pair scores; inference measured for20 only',
                        'K1 full12-scheme retrieval quality A/B remains unmeasured']})
    announce('complete', summary_path=str(output / 'matrix-summary.json'))
    return int(any(report['summary']['execution_errors'] or report['summary']['invalid_cases']
                   for report in all_reports.values()))


def resume_k3(args):
    """校验已完成的真实K3输出后续跑K4，避免重算已测embedding。"""
    os.environ.update(HF_HOME=str(args.hf_home), HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HUB_DISABLE_TELEMETRY='1', ANONYMIZED_TELEMETRY='False')
    import torch
    from transformers import AutoTokenizer

    torch.set_num_threads(args.threads)
    previous = args.resume_k3.resolve()
    backend = Path(__file__).resolve().parents[1]
    metadata = json.loads((previous / 'run-metadata.json').read_text(encoding='utf-8'))
    if metadata['dataset_hash'] != file_hash(args.dataset) or metadata['corpus_manifest_hash'] != file_hash(args.manifest):
        raise ValueError('resume snapshot hashes differ')
    if args.context_budget != metadata['context_budget_bge_tokens']:
        raise ValueError('resume context budget must match measured K3')
    corpus = load_manifest_corpus(args.manifest, backend.parent)
    cases = validate_core_dataset(args.dataset, corpus)
    details = json.loads(args.dataset.read_text(encoding='utf-8'))['case_metadata']
    original = json.loads((previous / 'chunk-manifest.json').read_text(encoding='utf-8'))
    chunks = {row['chunk_id']: CandidateChunk(**row) for row in original['chunks']}
    embedding_path, _ = _snapshot(args.hf_home, 'BAAI/bge-large-zh-v1.5')
    tokenizer = AutoTokenizer.from_pretrained(str(embedding_path), local_files_only=True, use_fast=True)
    tokenizer.model_max_length = 10 ** 9
    source_manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    documents = [{'node_id': row['node_id'], 'user_id': 1, 'title': row['title'], 'content': corpus[row['node_id']]}
                 for row in source_manifest['documents']]
    regenerated = chunk_documents(documents, tokenizer, ChunkConfig(**original['config']))
    if {chunk.chunk_id: asdict(chunk) for chunk in regenerated} != original_chunk_records(original):
        raise ValueError('resume chunks differ from current frozen tokenizer/source/config')
    reports = {name: json.loads((previous / f'k3-{name}.json').read_text(encoding='utf-8'))
               for name in ('dense', 'bm25', 'rrf')}
    pools = {}
    query_encoding_ms = {}
    for name in ('dense', 'bm25'):
        rows = {row['case_id']: row for row in reports[name]['cases']}
        if set(rows) != {case.case_id for case in cases}:
            raise ValueError('resume case ids differ')
        pools[name] = {}
        for case in cases:
            row = rows[case.case_id]
            if row['question'] != case.question:
                raise ValueError('resume question differs')
            step = next(step for step in row['steps'] if step.get('stage') == 'candidate_pool')
            pools[name][case.case_id] = [RankedChunk(chunks[identity], 0., name) for identity in step['chunk_ids']]
            if name == 'dense':
                timing = next(step for step in row['steps'] if step.get('stage') == 'timing')
                query_encoding_ms[case.case_id] = timing['uncached_query_encoding_ms']
    fused = {case.case_id: reciprocal_rank_fusion([pools['dense'][case.case_id], pools['bm25'][case.case_id]],
             user_id=1, k=metadata['rrf_k'], limit=20) for case in cases}
    output = args.output / datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True, exist_ok=False)
    metadata.update(original_k3_output=str(previous), resumed_at_utc=datetime.now(UTC).isoformat(),
                    baseline_code_hashes=metadata['code_hashes'],
                    code_hashes={name: file_hash(backend / name) for name in (
                        'eval/benchmark.py', 'eval/core_corpus.py', 'eval/retrieval_candidates.py',
                        'eval/run_retrieval_matrix.py', 'app/utils/markdown_cleaner.py')})
    for name, report in reports.items():
        _save(output / f'k3-{name}.json', report)
    _save(output / 'run-metadata.json', metadata)
    print(json.dumps({'stage': 'resume_k3', 'output': str(output), 'previous': str(previous)}, ensure_ascii=False), flush=True)
    if getattr(args, 'disabled_only', False):
        write_disabled_pool_reports(output=output, metadata=metadata, cases=cases, corpus=corpus,
            details=details, tokenizer=tokenizer, fused_pools=fused, query_encoding_ms=query_encoding_ms,
            context_budget=args.context_budget)
        print(json.dumps({'stage': 'disabled_controls_complete', 'output': str(output)}, ensure_ascii=False), flush=True)
        return 0
    return _run_reranker(args, output=output, metadata=metadata, cases=cases, corpus=corpus,
                         details=details, tokenizer=tokenizer, fused_pools=fused,
                         query_encoding_ms=query_encoding_ms, all_reports=reports)


def original_chunk_records(manifest):
    return {row['chunk_id']: row for row in manifest['chunks']}


def main(argv=None):
    backend = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=backend / 'eval/fixtures/core-rag-20261013.json')
    parser.add_argument('--manifest', type=Path, default=backend / 'eval/fixtures/core-rag-corpus-20261013.json')
    parser.add_argument('--hf-home', type=Path, default=Path('D:/AI_Models/huggingface'))
    parser.add_argument('--output', type=Path, default=backend / 'eval/reports/retrieval-matrix')
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--embedding-batch-size', type=int, default=8)
    parser.add_argument('--rerank-batch-size', type=int, default=4)
    parser.add_argument('--context-budget', type=int, default=1536)
    parser.add_argument('--resume-k3', type=Path)
    parser.add_argument('--disabled-only', action='store_true')
    args = parser.parse_args(argv)
    if args.disabled_only and not args.resume_k3:
        parser.error('--disabled-only requires --resume-k3 with measured candidate rankings')
    if min(args.threads, args.embedding_batch_size, args.rerank_batch_size, args.context_budget) < 1:
        parser.error('thread, batch and context budgets must be positive')
    def no_network(*unused_args, **unused_kwargs):
        raise RuntimeError('network disabled for local retrieval matrix')
    with patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network):
        return run(args)


if __name__ == '__main__':
    raise SystemExit(main())
