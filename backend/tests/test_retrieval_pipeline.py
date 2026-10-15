"""实际SQL归属与当前正文过滤先于候选打分及模型上下文。"""

from unittest.mock import Mock

import pytest

from app.models.node import KnowledgeNode


class Tokenizer:
    def __call__(self, text, *args, **kwargs):
        return {'input_ids': list(range(len(text) + 2))}


@pytest.mark.parametrize('mode', ['dense', 'bm25', 'hybrid'])
def test_candidate_excludes_foreign_deleted_and_stale_chunks_before_scoring(db, mode):
    from app.services.retrieval_pipeline import make_candidate_retrieval

    db.add_all([
        KnowledgeNode(id=1, user_id=7, title='Redis', content='Redis支持事务。'),
        KnowledgeNode(id=2, user_id=8, title='外部秘密', content='FOREIGN_SECRET'),
    ])
    db.commit()
    collection = Mock()
    collection.get.return_value = {
        'ids': ['1:0', '2:0', '3:0', '1:1'],
        'documents': ['Redis支持事务。', 'FOREIGN_SECRET', 'DELETED_SECRET', 'OLD_SECRET'],
        'embeddings': [[1., 0.], [1., 0.], [1., 0.], [1., 0.]],
        'metadatas': [{'node_id': 1}, {'node_id': 2}, {'node_id': 3}, {'node_id': 1}],
    }
    query_encoder = Mock(return_value=[1., 0.])
    reranker = Mock(return_value=[1.])
    candidate = make_candidate_retrieval(
        db, user_id=7, mode=mode, collection=collection, tokenizer=Tokenizer(),
        query_encoder=query_encoder, reranker=reranker, context_tokens=100,
    )
    result = candidate('Redis事务', user_id=7, top_k=3)

    assert [row['node_id'] for row in result] == [1]
    assert 'SECRET' not in str(result)
    assert reranker.call_args.args[0] == [('Redis事务', 'Redis\nRedis支持事务。')]
    assert candidate.trace['stale_rejected'] == 1
    assert candidate.trace['ownership_rejected'] == 2


def test_candidate_cannot_be_rebound_by_retrieval_argument(db):
    from app.services.retrieval_pipeline import make_candidate_retrieval

    candidate = make_candidate_retrieval(db, user_id=7, mode='bm25', tokenizer=Tokenizer())
    with pytest.raises(ValueError, match='user'):
        candidate('x', user_id=8, top_k=3)


def test_reranker_failure_is_visible_and_keeps_authorized_candidates(db):
    from app.services.retrieval_pipeline import make_candidate_retrieval

    db.add(KnowledgeNode(id=1, user_id=7, title='Redis', content='Redis支持事务。'))
    db.commit()
    collection = Mock()
    collection.get.return_value = {
        'ids': ['1:0'], 'documents': ['Redis支持事务。'],
        'metadatas': [{'node_id': 1}], 'embeddings': [[1., 0.]],
    }
    candidate = make_candidate_retrieval(
        db, user_id=7, mode='bm25', collection=collection, tokenizer=Tokenizer(),
        reranker=Mock(side_effect=TimeoutError('fixture')), context_tokens=100,
    )
    assert len(candidate('Redis', user_id=7, top_k=3)) == 1
    assert candidate.trace['rerank']['status'] == 'degraded'
