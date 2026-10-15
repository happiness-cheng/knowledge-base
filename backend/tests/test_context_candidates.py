"""相邻块的所有权、位置、去重与同预算验收。"""

import pytest

from eval.context_candidates import expand_neighbors
from eval.retrieval_candidates import CandidateChunk, RankedChunk, pack_context


def chunk(identity, node=7, owner=1, content='evidence'):
    return CandidateChunk(identity, node, owner, '', '', content, 1)


def test_neighbor_expansion_preserves_source_order_and_deduplicates():
    chunks = [chunk(str(i)) for i in range(4)]
    ranked = [RankedChunk(chunks[1], 2, 'rrf'), RankedChunk(chunks[2], 1, 'rrf')]
    result, trace = expand_neighbors(ranked, chunks, user_id=1, enabled=True)
    assert [item.chunk.chunk_id for item in result] == ['1', '0', '2', '3']
    assert trace['added_neighbors'] == 2


def test_neighbors_never_cross_document_or_owner_and_off_preserves_rank():
    chunks = [chunk('foreign', owner=2), chunk('other', node=8), chunk('owned'), chunk('next')]
    ranked = [RankedChunk(chunks[0], 100, 'rrf'), RankedChunk(chunks[2], 1, 'rrf')]
    result, _ = expand_neighbors(ranked, chunks, user_id=1, enabled=True)
    assert [item.chunk.chunk_id for item in result] == ['owned', 'next']
    off, trace = expand_neighbors(ranked, chunks, user_id=1, enabled=False)
    assert [item.chunk.chunk_id for item in off] == ['owned']
    assert trace['added_neighbors'] == 0


def test_mutated_or_missing_source_chunk_is_rejected():
    with pytest.raises(ValueError):
        expand_neighbors([RankedChunk(chunk('id', content='altered'), 1, 'rrf')],
                         [chunk('id')], user_id=1, enabled=True)


def test_neighbor_context_has_same_budget_and_keeps_whole_chunks():
    chunks = [chunk('first', content='abc'), chunk('second', content='def')]
    expanded, _ = expand_neighbors([RankedChunk(chunks[0], 1, 'rrf')], chunks, user_id=1, enabled=True)
    tokenizer = lambda text, **kwargs: {'input_ids': list(text)}
    packed, trace = pack_context(expanded, tokenizer, user_id=1, token_budget=3)
    assert [item.chunk.content for item in packed] == ['abc']
    assert trace['context_tokens'] == 3 and trace['skipped_budget'] == 1
