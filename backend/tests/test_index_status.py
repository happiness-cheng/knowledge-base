"""用户级索引状态：Chroma/RAGFlow 分支、失败列表、跨用户隔离。"""

from datetime import datetime, timezone

from app.config import settings
from app.models.index_job import IndexJob
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.models.user import User


def _current_user(db):
    return db.query(User).filter(User.username == "test-user").one()


def test_status_reports_chroma_default(client, db):
    response = client.get("/api/index-jobs/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["backend"] == "chroma"
    assert body["jobs"] == {"pending": 0, "running": 0, "failed": 0, "succeeded": 0}
    assert body["failed_jobs"] == []
    assert "chroma" in body


def test_status_reports_ragflow_documents_and_failed_jobs(client, db, monkeypatch):
    user = _current_user(db)
    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    db.add(RagflowDataset(
        user_id=user.id, dataset_id="ds-1", name="kb_user_1",
        embedding_model="BAAI/bge-large-zh-v1.5",
    ))
    db.add(RagflowDocument(
        user_id=user.id, node_id=7, document_id="doc-7",
        source_fingerprint="fp", state="failed", last_error="parse_failed",
    ))
    db.add(RagflowDocument(
        user_id=user.id, node_id=8, document_id="doc-8",
        source_fingerprint="fp", state="ready", last_error=None,
    ))
    db.add(IndexJob(
        user_id=user.id, node_id=7, generation=1, operation="upsert",
        state="failed", source_fingerprint="fp", attempts=3,
        next_attempt_at=datetime.now(timezone.utc).replace(tzinfo=None),
        last_error_type="RuntimeError", updated_at=datetime.now(timezone.utc).replace(tzinfo=None),
    ))
    db.commit()

    response = client.get("/api/index-jobs/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["backend"] == "ragflow"
    assert body["jobs"]["failed"] == 1
    assert body["failed_jobs"][0]["node_id"] == 7
    assert body["ragflow"]["dataset_id"] == "ds-1"
    assert body["ragflow"]["documents"] == {"failed": 1, "ready": 1}
    assert body["ragflow"]["failed_documents"][0]["node_id"] == 7
    assert body["ragflow"]["health"] is None


def test_status_does_not_leak_other_users_documents(client, db, monkeypatch):
    _current_user(db)
    other = User(username="other-status-user", hashed_password="x")
    db.add(other)
    db.flush()
    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    db.add(RagflowDocument(
        user_id=other.id, node_id=99, document_id="doc-99",
        source_fingerprint="fp", state="failed", last_error="parse_failed",
    ))
    db.commit()

    response = client.get("/api/index-jobs/status")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ragflow"]["documents"] == {}
    assert body["ragflow"]["failed_documents"] == []