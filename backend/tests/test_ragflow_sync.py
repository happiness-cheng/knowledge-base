"""RAGFlow 同步/检索适配：映射、指纹、失败状态、跨用户隔离。"""

import pytest

from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.models.user import User
from app.services.index_jobs import fingerprint
from app.services.ragflow_retrieval import retrieve_for_user
from app.services.ragflow_client import RagflowAPIError
from app.services.ragflow_sync import (
    STATE_FAILED,
    STATE_MISSING,
    STATE_PARSING,
    STATE_READY,
    delete_node,
    refresh_states,
    sync_node,
)


class FakeClient:
    def __init__(self):
        self.datasets = {}
        self.uploads = []
        self.deleted = []
        self.parsed = []
        self.metadata = []
        self.documents = {}
        self.chunks = []
        self.fail_update = False
        self.delete_error = None
        self._next = 1

    def ensure_dataset(self, name, *, embedding_model=""):
        if name not in self.datasets:
            self.datasets[name] = {
                "id": f"ds-{self._next}", "name": name,
                "embedding_model": embedding_model,
            }
            self._next += 1
        return self.datasets[name]

    def upload_document(self, dataset_id, filename, content, *, mime_type="text/markdown"):
        doc_id = f"doc-{self._next}"
        self._next += 1
        self.uploads.append((dataset_id, filename, content))
        self.documents[doc_id] = {"id": doc_id, "name": filename, "run": "UNSTART"}
        return self.documents[doc_id]

    def update_document_metadata(self, dataset_id, document_id, meta_fields):
        if self.fail_update:
            raise RuntimeError("metadata failed")
        self.metadata.append((dataset_id, document_id, meta_fields))

    def parse_documents(self, dataset_id, document_ids):
        self.parsed.append((dataset_id, list(document_ids)))

    def list_documents(self, dataset_id, *, document_id="", page_size=100):
        return [dict(doc) for doc in self.documents.values()]

    def delete_documents(self, dataset_id, document_ids):
        if self.delete_error is not None:
            raise self.delete_error
        for doc_id in document_ids:
            self.documents.pop(doc_id, None)
        self.deleted.append((dataset_id, list(document_ids)))

    def retrieve(self, question, dataset_ids, **kwargs):
        return list(self.chunks)


def make_user_and_node(db, *, username="u1", title="笔记", content="正文"):
    user = User(username=username, hashed_password="x")
    db.add(user)
    db.flush()
    node = KnowledgeNode(user_id=user.id, title=title, content=content)
    db.add(node)
    db.commit()
    db.refresh(node)
    return user, node


def test_sync_node_creates_dataset_upload_metadata_and_parse(db):
    user, node = make_user_and_node(db)
    client = FakeClient()

    result = sync_node(db, node, client)
    db.commit()

    assert result.changed is True
    assert result.state == STATE_PARSING
    dataset = db.get(RagflowDataset, user.id)
    assert dataset is not None
    assert dataset.dataset_id == "ds-1"
    row = db.get(RagflowDocument, (user.id, node.id))
    assert row.document_id == result.document_id
    assert row.source_fingerprint == fingerprint(node.title, node.content)
    assert row.state == STATE_PARSING
    assert client.uploads[0][1] == f"node-{node.id}.md"
    assert client.metadata[0][2]["node_id"] == str(node.id)
    assert client.parsed == [("ds-1", [result.document_id])]

    # 未变化时幂等，不再上传。
    again = sync_node(db, node, client)
    db.commit()
    assert again.changed is False
    assert len(client.uploads) == 1


def test_sync_node_content_change_replaces_document(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    first = sync_node(db, node, client)
    db.commit()

    node.content = "新正文"
    db.commit()
    second = sync_node(db, node, client)
    db.commit()

    assert second.document_id != first.document_id
    assert client.deleted == [("ds-1", [first.document_id])]
    row = db.get(RagflowDocument, (user.id, node.id))
    assert row.source_fingerprint == fingerprint(node.title, node.content)


def test_sync_failure_marks_failed_and_raises(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    client.fail_update = True

    with pytest.raises(RuntimeError, match="metadata failed"):
        sync_node(db, node, client)
    db.flush()

    row = db.get(RagflowDocument, (user.id, node.id))
    assert row.state == STATE_FAILED
    assert row.last_error == "RuntimeError"


def test_delete_node_removes_mapping_and_remote_document(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    sync_node(db, node, client)
    db.commit()
    doc_id = db.get(RagflowDocument, (user.id, node.id)).document_id

    assert delete_node(db, user.id, node.id, client) is True
    db.commit()

    assert db.get(RagflowDocument, (user.id, node.id)) is None
    assert client.deleted[-1] == ("ds-1", [doc_id])
    assert delete_node(db, user.id, node.id, client) is False


def test_delete_permission_error_is_not_swallowed(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    sync_node(db, node, client)
    db.commit()

    client.delete_error = RagflowAPIError(108, "no permission")
    node.content = "新正文"
    db.commit()

    with pytest.raises(RagflowAPIError, match="no permission"):
        sync_node(db, node, client)


def test_refresh_states_maps_done_failed_missing(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    result = sync_node(db, node, client)
    db.commit()

    client.documents[result.document_id]["run"] = "DONE"
    stats = refresh_states(db, user.id, client)
    db.commit()
    assert stats["updated"] == 1
    assert db.get(RagflowDocument, (user.id, node.id)).state == STATE_READY

    client.documents[result.document_id]["run"] = "FAIL"
    refresh_states(db, user.id, client)
    db.commit()
    assert db.get(RagflowDocument, (user.id, node.id)).state == STATE_FAILED

    client.documents.pop(result.document_id)
    stats = refresh_states(db, user.id, client)
    db.commit()
    assert stats["missing"] == 1
    assert db.get(RagflowDocument, (user.id, node.id)).state == STATE_MISSING


def test_retrieval_filters_unmapped_stale_and_duplicate_chunks(db):
    user, node = make_user_and_node(db)
    other_user, other_node = make_user_and_node(db, username="u2")
    client = FakeClient()
    result = sync_node(db, node, client)
    db.commit()
    other_result = sync_node(db, other_node, client)
    db.commit()
    client.chunks = [
        {"id": "c1", "document_id": result.document_id, "content": "证据一",
         "similarity": 0.9},
        {"id": "c2", "document_id": result.document_id, "content": "证据一",
         "similarity": 0.8},
        {"id": "c3", "document_id": "unknown-doc", "content": "未映射",
         "similarity": 0.7},
        {"id": "c4", "document_id": other_result.document_id, "content": "别人的",
         "similarity": 0.6},
    ]
    trace = []
    rows = retrieve_for_user(db, user_id=user.id, query="q", top_k=3,
                             client=client, trace=trace.append)
    assert [row["content"] for row in rows] == ["证据一"]
    assert rows[0]["node_id"] == node.id
    assert trace[0]["unmapped_chunks"] == 2
    assert trace[0]["stale_chunks"] == 0


def test_retrieval_stale_when_fingerprint_changed(db):
    user, node = make_user_and_node(db)
    client = FakeClient()
    result = sync_node(db, node, client)
    db.commit()
    node.content = "已修改但未同步"
    db.commit()
    client.chunks = [
        {"id": "c1", "document_id": result.document_id, "content": "旧证据",
         "similarity": 0.9},
    ]
    trace = []
    rows = retrieve_for_user(db, user_id=user.id, query="q", top_k=3,
                             client=client, trace=trace.append)
    assert rows == []
    assert trace[0]["stale_chunks"] == 1


def test_retrieval_without_dataset_returns_empty(db):
    user, _ = make_user_and_node(db)
    trace = []
    rows = retrieve_for_user(db, user_id=user.id, query="q", top_k=3,
                             client=FakeClient(), trace=trace.append)
    assert rows == []
    assert trace[0]["dataset"] is None