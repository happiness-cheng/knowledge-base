from unittest.mock import Mock

import pytest

from app.models.node import KnowledgeNode
from app.services import rag_service
from app.services.evidence_freshness import current_evidence
from app.services.index_jobs import fingerprint


def test_new_fingerprint_detects_title_and_body_changes():
    node = KnowledgeNode(id=1, user_id=2, title="new", content="same body")
    row = {"title": "old", "content": "same body", "source_fingerprint": fingerprint("old", "same body")}
    assert not current_evidence(row, node)
    row.update(title="new", source_fingerprint=fingerprint("new", "same body"))
    assert current_evidence(row, node)
    node.content = "changed"
    assert not current_evidence(row, node)


def test_legacy_chunks_require_current_title_and_body():
    node = KnowledgeNode(title="title", content="a\n b")
    assert current_evidence({"title": "title", "content": "a b"}, node)
    assert not current_evidence({"title": "title", "content": "old"}, node)


def test_delete_failure_propagates_for_durable_retry(monkeypatch):
    collection = Mock()
    collection.get.side_effect = OSError("fail")
    monkeypatch.setattr(rag_service, "_get_user_collection", lambda user: collection)
    with pytest.raises(OSError):
        rag_service.remove_node_from_index(1, 2)


def test_real_retrieval_excludes_stale_and_deleted_evidence(db, monkeypatch):
    from tests.conftest import TestSession

    db.add(KnowledgeNode(id=1, user_id=2, title="new", content="new body"))
    db.commit()
    collection = Mock()
    collection.query.return_value = {
        "ids": [["1:0", "99:0"]], "documents": [["old body", "deleted body"]],
        "metadatas": [[{"node_id": 1, "title": "old"}, {"node_id": 99, "title": "deleted"}]],
    }
    monkeypatch.setattr(rag_service, "SessionLocal", TestSession)
    monkeypatch.setattr(rag_service, "_get_existing_user_collection", lambda user: collection)
    monkeypatch.setattr(rag_service, "get_query_embedding", lambda query: [1, 0])
    assert rag_service.retrieve_relevant_nodes("q", user_id=2) == []


def test_langchain_custom_retrieval_cannot_bypass_freshness(db):
    from app.services.langchain_rag import AuthenticatedKBRetriever

    db.add(KnowledgeNode(id=1, user_id=2, title="new", content="new body"))
    db.commit()
    retriever = AuthenticatedKBRetriever(db=db, user_id=2, retrieval=lambda *a, **kw: [
        {"node_id": 1, "content": "old body"},
    ])
    assert retriever.invoke("q") == []


def test_reader_does_not_create_a_collection_or_load_model_when_index_absent(monkeypatch):
    from chromadb.errors import NotFoundError

    client = Mock()
    client.get_collection.side_effect = NotFoundError('collection absent')
    encoder = Mock(side_effect=AssertionError('empty index must not load model'))
    monkeypatch.setattr(rag_service, 'chroma_client', client)
    monkeypatch.setattr(rag_service, 'get_query_embedding', encoder)
    assert rag_service.retrieve_relevant_nodes('q', user_id=9) == []
    client.get_or_create_collection.assert_not_called()
    encoder.assert_not_called()


def test_candidate_reader_does_not_create_missing_index(db, monkeypatch):
    from chromadb.errors import NotFoundError
    from app.services.retrieval_pipeline import make_candidate_retrieval

    db.add(KnowledgeNode(id=1, user_id=1, title='title', content='body'))
    db.commit()
    client = Mock()
    client.get_collection.side_effect = NotFoundError('absent')
    monkeypatch.setattr(rag_service, 'chroma_client', client)
    candidate = make_candidate_retrieval(db, user_id=1, mode='bm25')
    with pytest.raises(ValueError, match='index collection'):
        candidate('q', user_id=1, top_k=1)
    client.get_or_create_collection.assert_not_called()
