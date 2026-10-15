from datetime import timedelta

from app.models.index_job import IndexJob
from app.models.node import KnowledgeNode
from app.services.index_jobs import enqueue, fingerprint, utc_now
from app.services.index_worker import run_once
from tests.conftest import TestSession
from tests.test_rag_index_updates import index as index  # noqa: PLC0414  显式重导出 pytest fixture。


def test_written_index_then_crash_replays_without_duplicate_chunks(db, index):
    db.add(KnowledgeNode(id=42, user_id=1, title="a", content="body|tail"))
    enqueue(db, 1, 42, "upsert", fingerprint("a", "body|tail"))
    db.commit()
    def crash_after_write(*args):
        index.add_node_to_index(*args)
        raise OSError("simulated response loss")
    assert run_once(TestSession, crash_after_write, index.remove_node_from_index) == "pending"
    assert run_once(TestSession, index.add_node_to_index, index.remove_node_from_index,
                    clock=lambda: utc_now() + timedelta(minutes=10)) == "succeeded"
    assert set(index._get_user_collection(1).get()["ids"]) == {"42:0", "42:1"}


def test_sql_update_during_old_write_converges_to_new_generation(db, index):
    db.add(KnowledgeNode(id=42, user_id=1, title="a", content="old|tail"))
    enqueue(db, 1, 42, "upsert", fingerprint("a", "old|tail"))
    db.commit()
    def write_old_then_commit_new(*args):
        index.add_node_to_index(*args)
        with TestSession() as session:
            node = session.get(KnowledgeNode, 42)
            node.title, node.content = "b", "new"
            enqueue(session, 1, 42, "upsert", fingerprint("b", "new"))
            session.commit()
    assert run_once(TestSession, write_old_then_commit_new, index.remove_node_from_index) == "superseded"
    db.expire_all()
    assert db.get(IndexJob, (1, 42)).state == "pending"
    assert run_once(TestSession, index.add_node_to_index, index.remove_node_from_index) == "succeeded"
    rows = index._get_user_collection(1).get()
    assert rows["ids"] == ["42:0"]
    assert rows["documents"] == ["new"]
    assert rows["metadatas"][0]["source_fingerprint"] == fingerprint("b", "new")
