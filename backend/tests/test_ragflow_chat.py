"""RAGFlow 后端接入严格 RAG 的分支：未配置/注入检索/模型只调一次。"""

from app.config import settings
from app.models.node import KnowledgeNode
from app.services.index_jobs import fingerprint
from app.services.langchain_rag import run_langchain_rag
from tests.test_langchain_rag import RecordingChatModel


def test_ragflow_backend_without_client_returns_explicit_error(db, monkeypatch):
    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    monkeypatch.setattr(
        "app.services.ragflow_client.get_ragflow_client", lambda *a, **kw: None,
    )
    model = RecordingChatModel()

    result = run_langchain_rag(db, "q", user_id=3, model=model)

    assert result["answer_status"] == "error"
    assert result["answer_error"] == "retrieval_backend_not_configured"
    assert model.calls == 0


def test_ragflow_backend_uses_ragflow_retrieval_and_sql_evidence(db, monkeypatch):
    db.add(KnowledgeNode(id=7, user_id=3, title="HTTP2", content="支持多路复用"))
    db.commit()
    marker = object()
    calls = {}

    def fake_retrieve(db_, *, user_id, query, top_k, client):
        calls.update(user_id=user_id, query=query, top_k=top_k, client=client)
        return [{"node_id": 7, "content": "支持多路复用"}]

    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    monkeypatch.setattr(
        "app.services.ragflow_client.get_ragflow_client", lambda *a, **kw: marker,
    )
    monkeypatch.setattr(
        "app.services.ragflow_retrieval.retrieve_for_user", fake_retrieve,
    )
    model = RecordingChatModel()

    result = run_langchain_rag(db, "HTTP2有什么特性？", user_id=3, model=model)

    assert result["answer_status"] == "supported"
    assert result["source_ids"] == [7]
    assert model.calls == 1
    assert calls["user_id"] == 3
    assert calls["client"] is marker
    assert calls["top_k"] == 3


def test_ragflow_chunk_with_uploaded_title_prefix_is_not_rejected_as_stale(db, monkeypatch):
    node = KnowledgeNode(id=7, user_id=3, title="HTTP2", content="支持多路复用")
    db.add(node)
    db.commit()

    def fake_retrieve(db_, *, user_id, query, top_k, client):
        return [{
            "node_id": 7,
            "content": "# HTTP2\n\n支持多路复用",
            "source_fingerprint": fingerprint(node.title, node.content),
            "evidence_verified": True,
        }]

    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    monkeypatch.setattr(
        "app.services.ragflow_client.get_ragflow_client", lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        "app.services.ragflow_retrieval.retrieve_for_user", fake_retrieve,
    )
    model = RecordingChatModel()

    result = run_langchain_rag(db, "HTTP2有什么特性？", user_id=3, model=model)

    assert result["answer_status"] == "supported"
    assert result["source_ids"] == [7]


def test_ragflow_chunk_with_wrong_fingerprint_is_rejected(db, monkeypatch):
    node = KnowledgeNode(id=7, user_id=3, title="HTTP2", content="支持多路复用")
    db.add(node)
    db.commit()

    def fake_retrieve(db_, *, user_id, query, top_k, client):
        return [{
            "node_id": 7,
            "content": "# HTTP2\n\n旧内容",
            "source_fingerprint": "wrong-fingerprint",
            "evidence_verified": True,
        }]

    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    monkeypatch.setattr(
        "app.services.ragflow_client.get_ragflow_client", lambda *a, **kw: object(),
    )
    monkeypatch.setattr(
        "app.services.ragflow_retrieval.retrieve_for_user", fake_retrieve,
    )
    model = RecordingChatModel()

    result = run_langchain_rag(db, "HTTP2有什么特性？", user_id=3, model=model)

    assert result["answer_status"] == "not_found"
    assert model.calls == 0