"""RAGFlow 索引对账：缺失/旧版本/孤儿/失败/手工项与修复任务。"""

from app.config import settings
from app.models.index_job import IndexJob
from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.models.user import User
from app.services.index_jobs import fingerprint
from app.services.ragflow_reconcile import (
    apply_user_ragflow_repair,
    reconcile_user_ragflow,
)


def _add_user(db, username="u1"):
    user = User(username=username, hashed_password="x")
    db.add(user)
    db.flush()
    return user


def _add_node(db, user_id, node_id, title="t", content="body"):
    node = KnowledgeNode(id=node_id, user_id=user_id, title=title, content=content)
    db.add(node)
    return node


def _add_mapping(db, user_id, node_id, document_id, fp, state="ready"):
    db.add(RagflowDocument(
        user_id=user_id, node_id=node_id, document_id=document_id,
        source_fingerprint=fp, state=state,
    ))


def test_reconcile_classifies_missing_stale_orphan_failed_and_manual(db):
    user = _add_user(db)
    other = _add_user(db, "u2")
    _add_node(db, user.id, 1, "ok", "body")
    _add_node(db, user.id, 2, "stale", "new body")
    _add_node(db, user.id, 3, "empty", "")
    _add_node(db, user.id, 4, "missing", "body4")
    _add_node(db, user.id, 5, "failed", "body5")
    _add_node(db, user.id, 6, "parsing", "body6")
    db.add(RagflowDataset(user_id=user.id, dataset_id="ds-1", name="kb_user_1"))
    _add_mapping(db, user.id, 1, "doc-1", fingerprint("ok", "body"))
    _add_mapping(db, user.id, 2, "doc-2", "old")
    _add_mapping(db, user.id, 5, "doc-5", fingerprint("failed", "body5"), "failed")
    _add_mapping(db, user.id, 6, "doc-6", fingerprint("parsing", "body6"), "parsing")
    _add_mapping(db, user.id, 99, "doc-99", "fp")
    _add_mapping(db, other.id, 1, "doc-other", "fp")
    db.commit()

    report = reconcile_user_ragflow(db, user.id)

    assert report["missing_node_ids"] == [4]
    assert report["orphan_node_ids"] == [99]
    assert report["stale_node_ids"] == [2]
    assert report["empty_content_node_ids"] == [3]
    assert report["failed_node_ids"] == [5]
    assert report["parsing_node_ids"] == [6]
    assert report["health"] == "unhealthy"
    assert report["repair_actions"]["upsert_node_ids"] == [2, 4, 5]
    assert report["repair_actions"]["delete_node_ids"] == [99]
    assert report["repair_actions"]["manual_node_ids"] == [3]
    assert "missing_documents:1" in report["errors"]


def test_apply_enqueues_only_current_users_actions(db):
    user = _add_user(db)
    _add_node(db, user.id, 4, "missing", "body4")
    _add_node(db, user.id, 5, "failed", "body5")
    _add_mapping(db, user.id, 5, "doc-5", fingerprint("failed", "body5"), "failed")
    _add_mapping(db, user.id, 99, "doc-99", "fp")
    db.add(RagflowDataset(user_id=user.id, dataset_id="ds-1", name="kb_user_1"))
    db.commit()
    report = reconcile_user_ragflow(db, user.id)

    enqueued = apply_user_ragflow_repair(db, report)
    db.commit()

    assert enqueued == {"upsert": 2, "delete": 1}
    jobs = {(job.node_id, job.operation) for job in db.query(IndexJob).all()}
    assert jobs == {(4, "upsert"), (5, "upsert"), (99, "delete")}


def test_reconcile_api_dry_run_and_apply(client, db, monkeypatch):
    user = db.query(User).filter(User.username == "test-user").one()
    _add_node(db, user.id, 7, "note", "body")
    db.add(RagflowDataset(user_id=user.id, dataset_id="ds-1", name="kb_user_1"))
    db.commit()
    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")

    dry = client.post("/api/index-jobs/reconcile")
    assert dry.status_code == 200, dry.text
    assert dry.json()["missing_node_ids"] == [7]
    assert db.query(IndexJob).count() == 0

    applied = client.post("/api/index-jobs/reconcile?apply=true")
    assert applied.status_code == 200, applied.text
    assert applied.json()["enqueued"] == {"upsert": 1, "delete": 0}
    assert db.query(IndexJob).count() == 1


def test_reconcile_api_rejects_chroma_backend(client):
    response = client.post("/api/index-jobs/reconcile")
    assert response.status_code == 400