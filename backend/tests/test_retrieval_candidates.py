"""候选切片、授权过滤、融合、预算和精排降级走公开接口验证。"""

import pytest


class FixtureTokenizer:
    """单元测试逐字符 token 桩；真实实验必须提供真实 BGE tokenizer。"""
    def __call__(self, text, text_pair=None, *, add_special_tokens=True,
                 return_offsets_mapping=False, **kwargs):
        value = text + (text_pair or '')
        result = {'input_ids': list(range(len(value) + (2 if add_special_tokens else 0)))}
        if return_offsets_mapping:
            result['offset_mapping'] = [(index, index + 1) for index in range(len(value))]
        return result


def _chunk(chunk_id, node_id=1, user_id=7, content='证据'):
    from eval.retrieval_candidates import CandidateChunk

    return CandidateChunk(chunk_id, node_id, user_id, '标题', '小节', content, 8)


def test_fixed_chunks_use_full_encoded_input_budget_and_stable_ids():
    from eval.retrieval_candidates import ChunkConfig, chunk_documents

    documents = [{'node_id': 1, 'user_id': 7, 'title': '标题', 'content': '甲乙丙丁戊己庚辛壬癸'}]
    tokenizer = FixtureTokenizer()
    config = ChunkConfig('fixed', body_tokens=8, overlap_tokens=2, model_limit=12)
    first = chunk_documents(documents, tokenizer, config)
    second = chunk_documents(documents, tokenizer, config)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert len(first) > 1
    assert all(chunk.token_count == len(tokenizer(chunk.embedding_text)['input_ids']) <= 12 for chunk in first)
    assert ''.join(chunk.content for chunk in first).startswith('甲乙丙丁')


def test_heading_chunks_reuse_indented_heading_rules_without_app_import():
    from eval.retrieval_candidates import ChunkConfig, chunk_documents

    documents = [{'node_id': 1, 'user_id': 7, 'title': '文档',
                  'content': '  ## 第一节\n甲乙丙\n  ## 第二节\n丁戊己'}]
    chunks = chunk_documents(documents, FixtureTokenizer(), ChunkConfig('heading', 32, 0, 64))
    assert [chunk.heading for chunk in chunks] == ['第一节', '第二节']
    assert chunks[0].content == '甲乙丙'
    assert chunks[1].content == '丁戊己'


def test_chunking_rejects_prefix_overflow_and_nonprogressing_overlap():
    from eval.retrieval_candidates import ChunkConfig, chunk_documents

    with pytest.raises(ValueError, match='overlap'):
        ChunkConfig('fixed', 8, 8, 32)
    with pytest.raises(ValueError, match='prefix'):
        chunk_documents([{'node_id': 1, 'user_id': 7, 'title': '超长标题' * 8,
                          'content': '正文'}], FixtureTokenizer(), ChunkConfig('fixed', 8, 0, 12))


def test_short_final_section_below_overlap_budget_is_kept_without_next_window():
    from eval.retrieval_candidates import ChunkConfig, chunk_documents

    documents = [{'node_id': 1, 'user_id': 7, 'title': '文档', 'content': '## 小节\n甲乙'}]
    tokenizer = FixtureTokenizer()
    baseline = chunk_documents(documents, tokenizer, ChunkConfig('heading', 8, 0, 32))
    overlapped = chunk_documents(documents, tokenizer, ChunkConfig('heading', 8, 4, 32))
    assert [chunk.content for chunk in overlapped] == [chunk.content for chunk in baseline] == ['甲乙']
    assert overlapped[0].token_count <= 32


def test_dense_filters_unauthorized_users_before_candidate_scoring():
    from eval.retrieval_candidates import dense_rank

    chunks = [_chunk('other', user_id=8), _chunk('mine-a'), _chunk('mine-b')]
    scores = dense_rank([1., 0.], chunks, [[100., 0.], [.5, 0.], [.9, 0.]], user_id=7, limit=2)
    assert [item.chunk.chunk_id for item in scores] == ['mine-b', 'mine-a']
    assert [item.score for item in scores] == pytest.approx([.9, .5])


def test_bm25_fits_only_authorized_documents_and_handles_empty_query():
    from eval.retrieval_candidates import BM25Retriever

    chunks = [_chunk('other', user_id=8, content='秘密词'),
              _chunk('mine-a', content='apple banana'), _chunk('mine-b', content='banana banana')]
    seen = []
    def tokenize(text):
        seen.append(text)
        return text.split()
    retriever = BM25Retriever(chunks, user_id=7, tokenize=tokenize)
    assert all('秘密词' not in text for text in seen)
    assert all(item.chunk.user_id == 7 for item in retriever.rank('apple', 2))
    assert retriever.rank('', 2) == []


def test_rrf_uses_filtered_unique_ranks_and_ignores_incomparable_raw_scores():
    from eval.retrieval_candidates import RankedChunk, reciprocal_rank_fusion

    one, two = _chunk('one'), _chunk('two')
    other = _chunk('other', user_id=8)
    result = reciprocal_rank_fusion([
        [RankedChunk(other, 999, 'dense'), RankedChunk(one, .001, 'dense'),
         RankedChunk(one, 999, 'dense'), RankedChunk(two, .99, 'dense')],
        [RankedChunk(two, 100, 'bm25'), RankedChunk(one, 0, 'bm25')],
    ], user_id=7, k=60, limit=10)
    assert len(result) == 2
    assert all(item.chunk.user_id == 7 for item in result)
    assert all(item.score == pytest.approx(1 / 61 + 1 / 62) for item in result)


def test_context_packing_counts_actual_full_text_and_never_exceeds_budget():
    from eval.retrieval_candidates import RankedChunk, pack_context

    ranked = [RankedChunk(_chunk('one', content='甲乙丙丁'), 1, 'dense'),
              RankedChunk(_chunk('other', user_id=8), 100, 'dense'),
              RankedChunk(_chunk('two', node_id=2, content='戊己庚辛'), .5, 'dense')]
    packed, counts = pack_context(ranked, FixtureTokenizer(), user_id=7, token_budget=15)
    assert [item.chunk.chunk_id for item in packed] == ['one']
    assert counts['context_tokens'] <= 15
    assert counts['skipped_budget'] == 1
    assert counts['unauthorized_filtered'] == 1


def test_reranker_can_be_disabled_and_failures_explicitly_preserve_base_order():
    from eval.retrieval_candidates import RankedChunk, rerank_candidates

    ranked = [RankedChunk(_chunk('one'), 1, 'rrf'), RankedChunk(_chunk('two'), .5, 'rrf')]
    def fail(_):
        raise RuntimeError('model unavailable')
    disabled, disabled_trace = rerank_candidates('问题', ranked, fail, user_id=7, pool_size=2, enabled=False)
    assert disabled == ranked
    assert disabled_trace['status'] == 'disabled'
    fallback, trace = rerank_candidates('问题', ranked, fail, user_id=7, pool_size=2)
    assert fallback == ranked
    assert trace['status'] == 'degraded'
    assert trace['error_type'] == 'RuntimeError'


def test_reranker_filters_users_sorts_real_scores_and_reports_pair_truncation():
    from eval.retrieval_candidates import RankedChunk, rerank_candidates

    ranked = [RankedChunk(_chunk('other', user_id=8), 100, 'rrf'),
              RankedChunk(_chunk('one', content='甲乙丙丁'), 1, 'rrf'),
              RankedChunk(_chunk('two', content='短'), .5, 'rrf')]
    seen = []
    def predict(pairs):
        seen.extend(pairs)
        return [.1, .9]
    reranked, trace = rerank_candidates('很长的问题', ranked, predict, user_id=7, pool_size=2,
                                       tokenizer=FixtureTokenizer(), max_length=16)
    assert [item.chunk.chunk_id for item in reranked] == ['two', 'one']
    assert len(seen) == 2
    assert trace['status'] == 'ok'
    assert trace['pairs'] == 2
    assert trace['pair_truncated'] == 1


def test_chunk_config_selection_uses_development_coverage_without_heldout_labels():
    from eval.run_retrieval_matrix import select_chunk_config

    candidates = [
        {'config': {'strategy': 'fixed', 'body_tokens': 256}, 'chunk_count': 9, 'cases': [
            {'split': 'development', 'evidence_covered': 1, 'evidence_targets': 2, 'all_covered': 0},
            {'split': 'heldout', 'evidence_covered': 2, 'evidence_targets': 2, 'all_covered': 1},
        ]},
        {'config': {'strategy': 'heading', 'body_tokens': 384}, 'chunk_count': 10, 'cases': [
            {'split': 'development', 'evidence_covered': 2, 'evidence_targets': 2, 'all_covered': 1},
            {'split': 'heldout', 'evidence_covered': 0, 'evidence_targets': 2, 'all_covered': 0},
        ]},
    ]
    assert select_chunk_config(candidates)['strategy'] == 'heading'


def test_rrf_parameter_selection_accepts_only_development_summaries():
    from eval.run_retrieval_matrix import select_rrf_k

    assert select_rrf_k({
        20: {'evidence_all_covered': .5, 'evidence_coverage': .7, 'document_recall_at_3': .8},
        60: {'evidence_all_covered': .6, 'evidence_coverage': .7, 'document_recall_at_3': .8},
        120: {'evidence_all_covered': .5, 'evidence_coverage': .9, 'document_recall_at_3': 1},
    }) == 60


def test_oracle_chunk_coverage_does_not_merge_partial_blocks_into_complete_evidence():
    from eval.benchmark import BenchmarkCase, EvidenceTarget
    from eval.run_retrieval_matrix import oracle_chunk_report

    case = BenchmarkCase('one', '问题', gold_evidence=[EvidenceTarget(1, '开始', '结束')])
    result = oracle_chunk_report([case], [_chunk('one', content='开始 中间'),
                                        _chunk('two', content='中间 结束')],
                                 {'one': {'split': 'development'}})
    assert result[0]['evidence_covered'] == 0
    assert result[0]['evidence_targets'] == 1
    assert result[0]['all_covered'] == 0


def test_matrix_never_expands_real_reranker_token_limit_for_untruncated_counting(tmp_path, monkeypatch):
    import json
    from hashlib import sha256
    from pathlib import Path
    from types import SimpleNamespace

    import numpy as np
    import sentence_transformers
    import transformers

    from eval import run_retrieval_matrix as matrix

    class Embedding:
        max_seq_length = 512
        def __init__(self, *args, **kwargs):
            pass
        def get_sentence_embedding_dimension(self):
            return 1024
        def encode(self, texts, **kwargs):
            return np.array([1., 0.]) if isinstance(texts, str) else np.ones((len(texts), 2))
    class Reranker:
        def __init__(self, *args, max_length, **kwargs):
            self.tokenizer = FixtureTokenizer()
            self.tokenizer.model_max_length = max_length
        @property
        def max_seq_length(self):
            return self.tokenizer.model_max_length
        def predict(self, pairs, **kwargs):
            assert self.max_seq_length == 512, '真实模型预算被计数逻辑改变'
            return [float(index) for index in range(len(pairs))]
    monkeypatch.setattr(sentence_transformers, 'SentenceTransformer', Embedding)
    monkeypatch.setattr(sentence_transformers, 'CrossEncoder', Reranker)
    monkeypatch.setattr(transformers.AutoTokenizer, 'from_pretrained', lambda *a, **kw: FixtureTokenizer())
    monkeypatch.setattr(matrix, '_snapshot', lambda *a: (tmp_path, 'a' * 40))
    backend = Path(__file__).resolve().parents[1]
    original_manifest = json.loads((backend / 'eval/fixtures/core-rag-corpus-20261013.json').read_text(encoding='utf-8'))
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'frozen_at': '2026-10-13',
        'documents': [original_manifest['documents'][0]]}), encoding='utf-8')
    dataset = tmp_path / 'dataset.json'
    dataset.write_text(json.dumps({
        'schema_version': 1, 'metadata': {'frozen_at': '2026-10-13', 'blind_test': False,
                                         'corpus_manifest_sha256': sha256(manifest.read_bytes()).hexdigest()},
        'cases': [{'case_id': 'one', 'question': '进程是什么', 'query_source': 'agent_simulated',
                   'gold_evidence': [{'node_id': 1001, 'head': '进程是资源分配的基本单位。'}]}],
        'case_metadata': {'one': {'topic': 'os', 'template_group': 'process', 'split': 'development',
                                 'query_category': 'semantic_rephrase', 'evidence_ranges': ['进程定义']}},
    }), encoding='utf-8')
    args = SimpleNamespace(
        hf_home=Path('D:/AI_Models/huggingface'), device='cpu', threads=1,
        dataset=dataset, manifest=manifest,
        output=tmp_path, embedding_batch_size=8, rerank_batch_size=4, context_budget=1536,
    )
    assert matrix.run(args) == 0
    report = json.loads(next(tmp_path.glob('*/k4-rrf_reranker_20.json')).read_text(encoding='utf-8'))
    assert report['reranker_degradations'] == 0


def test_disabled_reranker_controls_match_each_candidate_pool_instead_of_shared_top20(tmp_path):
    from eval.benchmark import BenchmarkCase, EvidenceTarget
    from eval.retrieval_candidates import RankedChunk
    from eval.run_retrieval_matrix import write_disabled_pool_reports

    case = BenchmarkCase('one', '问题', gold_evidence=[EvidenceTarget(10, '证据')])
    pools = {'one': [RankedChunk(_chunk(str(index), node_id=index, user_id=1), 1 / index, 'rrf')
                     for index in range(1, 11)]}
    reports = write_disabled_pool_reports(output=tmp_path, metadata={'mode': 'retrieval'},
        cases=[case], corpus={index: '证据' for index in range(1, 11)},
        details={'one': {'split': 'development'}}, tokenizer=FixtureTokenizer(), fused_pools=pools,
        query_encoding_ms={'one': 1.}, context_budget=500)
    assert reports['rrf_off_5']['summary']['evidence_covered'] == 0
    assert reports['rrf_off_10']['summary']['evidence_covered'] == 1
