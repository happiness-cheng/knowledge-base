import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy import event, update

from app.models.node import KnowledgeNode
from app.services import agent_tools, rag_service
from app.services.agent_service import run_agent
from app.services.index_jobs import fingerprint
from tests.conftest import TEST_ENGINE, TestSession


def test_search_tool_preserves_verified_source_version(monkeypatch):
    expected = fingerprint('title', 'body')
    monkeypatch.setattr(agent_tools, 'retrieve_relevant_nodes', lambda *a, **kw: [
        {'node_id': 1, 'title': 'title', 'content': 'body', 'source_fingerprint': expected},
    ])
    result = json.loads(agent_tools._handle_search({'query': 'q'}, None, user_id=1))
    assert result[0]['source_fingerprint'] == expected


def test_cached_sqlalchemy_node_cannot_authorize_stale_tool_body(db, monkeypatch):
    node = KnowledgeNode(id=1, user_id=1, title='old', content='OLD_BODY')
    db.add(node)
    db.commit()
    assert db.get(KnowledgeNode, 1).content == 'OLD_BODY'
    with TestSession() as writer:
        writer.execute(update(KnowledgeNode).where(KnowledgeNode.id == 1).values(
            title='new', content='CURRENT_BODY'))
        writer.commit()
    client = Mock()
    client.chat_with_tools.side_effect = [SimpleNamespace(content=[SimpleNamespace(
        type='tool_use', name='search_knowledge_base', id='search', input={'query': 'q'},
    )]), SimpleNamespace(content=[SimpleNamespace(text='{"status":"not_found","answer":"","source_ids":[]}')])]
    monkeypatch.setattr('app.services.agent_service.execute_tool', lambda *a, **kw: json.dumps([
        {'node_id': 1, 'content': 'OLD_BODY', 'source_fingerprint': fingerprint('old', 'OLD_BODY')},
    ]))
    observed = []
    result = run_agent(db, SimpleNamespace(messages=[]), 'q', user_id=1, kb_only=True,
        ai_client=client, observe_tool_result=lambda *args: observed.append(args))
    assert result['answer_status'] == 'not_found'
    assert 'OLD_BODY' not in str(observed)


def test_scoped_date_failure_never_falls_back_to_other_users(db, monkeypatch):
    db.add_all([
        KnowledgeNode(id=1, user_id=1, title='2026-10-01 own', content='own', created_at=datetime(2026, 10, 1)),
        KnowledgeNode(id=2, user_id=2, title='2099-12-31 private', content='private', created_at=datetime(2099, 12, 31)),
    ])
    db.commit()
    monkeypatch.setattr(rag_service, 'SessionLocal', TestSession)
    def fail_scoped_latest(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().startswith('SELECT knowledge_nodes.title') and 'knowledge_nodes.user_id =' in statement:
            raise RuntimeError('scoped date query failed')
    event.listen(TEST_ENGINE, 'before_cursor_execute', fail_scoped_latest)
    try:
        result = rag_service._attach_note_dates([{'node_id': 1}], user_id=1)
        assert result[0]['note_date'] == '2026-10-01'
        assert result[0]['kb_latest_date'] == ''
    finally:
        event.remove(TEST_ENGINE, 'before_cursor_execute', fail_scoped_latest)


@pytest.mark.parametrize('backend', ['langchain', 'candidate'])
def test_all_retrievers_refresh_cached_sql_before_using_evidence(db, backend):
    node = KnowledgeNode(id=1, user_id=1, title='old', content='OLD_BODY')
    db.add(node)
    db.commit()
    assert node.content == 'OLD_BODY'
    with TestSession() as writer:
        writer.execute(update(KnowledgeNode).where(KnowledgeNode.id == 1).values(
            title='new', content='CURRENT_BODY'))
        writer.commit()
    rows = [{'node_id': 1, 'title': 'old', 'content': 'OLD_BODY',
             'source_fingerprint': fingerprint('old', 'OLD_BODY')}]
    if backend == 'langchain':
        from app.services.langchain_rag import AuthenticatedKBRetriever
        assert AuthenticatedKBRetriever(db=db, user_id=1, retrieval=lambda *a, **kw: rows).invoke('q') == []
    else:
        from app.services.retrieval_pipeline import make_candidate_retrieval
        collection = SimpleNamespace(get=lambda **kwargs: {
            'ids': ['1:0'], 'documents': ['OLD_BODY'], 'metadatas': [rows[0]], 'embeddings': [[1.0, 0.0]],
        })
        tokenizer = lambda text, **kwargs: {'input_ids': list(range(len(text)))}
        candidate = make_candidate_retrieval(db, user_id=1, mode='bm25', collection=collection,
                                            tokenizer=tokenizer)
        with pytest.raises(ValueError, match='current evidence'):
            candidate('OLD_BODY', user_id=1, top_k=1)
