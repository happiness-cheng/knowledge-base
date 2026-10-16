"""通过真实 Chroma 集合验证单个笔记的索引替换，不调用联网模型。"""

import hashlib
import math
from uuid import uuid4

import pytest

from app.services import rag_service
from app.services.index_jobs import fingerprint


def _fixed_chunks(content):
    return [(f"小节 {i}", part) for i, part in enumerate(content.split("|"))] if content else []


def _offline_embedding(text):
    values = [float(value + 1) for value in hashlib.sha256(text.encode()).digest()[:4]]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


class _CountingTokenizer:
    def __call__(self, text, **kwargs):
        return {"input_ids": list(range(len(text) + 2))}


@pytest.fixture
def index(monkeypatch, chroma_server_client):
    # 与 production 同样通过服务访问索引；唯一集合名隔离测试数据。
    monkeypatch.setattr(rag_service, "chroma_client", chroma_server_client)
    monkeypatch.setattr(rag_service, "_SUFFIX", f"_index_update_{uuid4().hex}")
    monkeypatch.setattr(rag_service, "split_by_headings", _fixed_chunks)
    monkeypatch.setattr(rag_service, "get_embedding", _offline_embedding)
    monkeypatch.setattr(rag_service, "_get_tokenizer", lambda: _CountingTokenizer())
    return rag_service


def _rows(collection):
    result = collection.get(include=["documents", "metadatas", "embeddings"])
    return {
        chunk_id: {
            "document": result["documents"][i],
            "metadata": result["metadatas"][i],
            "embedding": result["embeddings"][i].tolist(),
        }
        for i, chunk_id in enumerate(result["ids"])
    }


def test_shortening_three_chunks_to_one_removes_old_tail(index):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", "旧标题", user_id=4)
    index.add_node_to_index(7, "新首段", "新标题", user_id=4)

    rows = _rows(index._get_user_collection(4))
    assert set(rows) == {"7:0"}
    assert rows["7:0"]["document"] == "新首段"
    assert rows["7:0"]["metadata"]["title"] == "新标题"


def test_empty_content_removes_all_previously_indexed_chunks(index):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", user_id=4)
    index.add_node_to_index(7, "", user_id=4)

    assert _rows(index._get_user_collection(4)) == {}


def test_adding_and_expanding_updates_documents_vectors_and_metadata(index):
    index.add_node_to_index(7, "首段", "旧标题", user_id=4)
    old_rows = _rows(index._get_user_collection(4))
    assert set(old_rows) == {"7:0"}

    index.add_node_to_index(7, "新首段|新中段|新尾段", "新标题", user_id=4)
    rows = _rows(index._get_user_collection(4))
    assert set(rows) == {"7:0", "7:1", "7:2"}
    for i, document in enumerate(["新首段", "新中段", "新尾段"]):
        row = rows[f"7:{i}"]
        assert row["document"] == document
        assert row["metadata"] == {
            "title": "新标题", "node_id": 7, "chunk_index": i, "heading": f"小节 {i}",
            "source_fingerprint": fingerprint("新标题", "新首段|新中段|新尾段"),
            "embedding_tokens": 14, "embedding_header_shortened": False,
        }
        assert row["embedding"] == pytest.approx(_offline_embedding(f"新标题\n小节 {i}\n{document}"))
    assert rows["7:0"]["embedding"] != old_rows["7:0"]["embedding"]


@pytest.mark.parametrize("replacement", ["新首段", ""])
def test_replacing_a_node_preserves_other_nodes_and_users(index, replacement):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", user_id=4)
    index.add_node_to_index(8, "另一篇首段|另一篇尾段", user_id=4)
    index.add_node_to_index(7, "另一个用户的首段|另一个用户的尾段", user_id=5)
    same_user_before = _rows(index._get_user_collection(4))
    other_node_before = {key: row for key, row in same_user_before.items() if row["metadata"]["node_id"] == 8}
    other_user_before = _rows(index._get_user_collection(5))

    index.add_node_to_index(7, replacement, user_id=4)

    rows = _rows(index._get_user_collection(4))
    assert {key: row for key, row in rows.items() if row["metadata"]["node_id"] == 8} == other_node_before
    assert _rows(index._get_user_collection(5)) == other_user_before
    assert {key for key, row in rows.items() if row["metadata"]["node_id"] == 7} == ({"7:0"} if replacement else set())


def test_other_collections_do_not_make_an_existing_nodes_vectors_unreadable(index):
    """覆盖原故障：元数据还在，但内存向量索引淘汰后 get 报错、query 为空。"""
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", user_id=4)
    anchor = index._get_user_collection(4)
    before = _rows(anchor)
    for i in range(512):
        collection = index.chroma_client.create_collection(f"pressure_{uuid4().hex}_{i}")
        collection.upsert(ids=["8:0"], documents=["其他内容"], embeddings=[_offline_embedding("其他内容")])
    assert _rows(anchor) == before
    result = anchor.query(query_embeddings=[_offline_embedding("旧首段")], n_results=3)
    assert set(result["ids"][0]) == set(before)


@pytest.mark.parametrize("legacy_metadata", [{"title": "旧标题"}, {"title": "旧标题", "node_id": 7}])
@pytest.mark.parametrize("replacement", ["新正文", ""])
def test_replacing_removes_legacy_single_id(index, legacy_metadata, replacement):
    collection = index._get_user_collection(4)
    collection.upsert(ids=["7"], documents=["旧版完整正文"],
                      embeddings=[_offline_embedding("旧版完整正文")], metadatas=[legacy_metadata])
    index.add_node_to_index(7, "旧首段|旧尾段", user_id=4)
    # 同时残留旧单 ID 与分块 ID，模拟混合版本索引。
    collection.upsert(ids=["7"], documents=["旧版完整正文"],
                      embeddings=[_offline_embedding("旧版完整正文")], metadatas=[legacy_metadata])

    index.add_node_to_index(7, replacement, user_id=4)

    rows = _rows(collection)
    assert set(rows) == ({"7:0"} if replacement else set())


def test_unchanged_input_can_be_replayed_without_duplicate_chunks(index):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", user_id=4)
    index.add_node_to_index(7, "新首段|新尾段", "新标题", user_id=4)
    expected = _rows(index._get_user_collection(4))

    index.add_node_to_index(7, "新首段|新尾段", "新标题", user_id=4)

    assert _rows(index._get_user_collection(4)) == expected


def test_no_chunks_clears_a_node_without_upserting_an_empty_batch(index, monkeypatch):
    index.add_node_to_index(7, "旧首段|旧尾段", user_id=4)
    monkeypatch.setattr(index, "split_by_headings", lambda content: [])

    index.add_node_to_index(7, "没有有效切片的正文", user_id=4)

    assert _rows(index._get_user_collection(4)) == {}


def test_embedding_failure_preserves_all_old_chunks_and_replay_converges(index, monkeypatch):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", "旧标题", user_id=4)
    collection = index._get_user_collection(4)
    before = _rows(collection)
    failed = False

    def fail_on_middle_chunk_once(text):
        nonlocal failed
        if "新中段" in text and not failed:
            failed = True
            raise RuntimeError("injected embedding failure")
        return _offline_embedding(text)

    monkeypatch.setattr(index, "get_embedding", fail_on_middle_chunk_once)
    with pytest.raises(RuntimeError, match="injected embedding failure"):
        index.add_node_to_index(7, "新首段|新中段", "新标题", user_id=4)
    assert _rows(collection) == before

    index.add_node_to_index(7, "新首段|新中段", "新标题", user_id=4)
    rows = _rows(collection)
    assert set(rows) == {"7:0", "7:1"}
    assert [rows[f"7:{i}"]["document"] for i in range(2)] == ["新首段", "新中段"]


class _FailOnceCollection:
    """只在指定的单次操作边界注入故障，其余操作走真实 Chroma。"""

    def __init__(self, collection, operation, *, after=False):
        self.collection = collection
        self.operation = operation
        self.after = after
        self.failed = False

    def __getattr__(self, name):
        method = getattr(self.collection, name)
        if name != self.operation:
            return method

        def fail_once(*args, **kwargs):
            if self.failed:
                return method(*args, **kwargs)
            self.failed = True
            if self.after:
                method(*args, **kwargs)
            raise RuntimeError(f"injected {name} failure")

        return fail_once


@pytest.mark.parametrize("operation,after", [
    ("upsert", False), ("upsert", True), ("get", False),
    ("delete", False), ("delete", True),
])
def test_storage_failure_is_observable_and_same_input_replay_converges(index, monkeypatch, operation, after):
    index.add_node_to_index(7, "旧首段|旧中段|旧尾段", "旧标题", user_id=4)
    collection = index._get_user_collection(4)
    before = _rows(collection)
    failing_collection = _FailOnceCollection(collection, operation, after=after)
    monkeypatch.setattr(index, "_get_user_collection", lambda user_id: failing_collection)

    with pytest.raises(RuntimeError, match=f"injected {operation} failure"):
        index.add_node_to_index(7, "新首段", "新标题", user_id=4)

    intermediate = _rows(collection)
    if operation == "upsert" and not after:
        assert intermediate == before
    else:
        assert intermediate["7:0"]["document"] == "新首段"
        assert set(intermediate) == ({"7:0"} if operation == "delete" and after else {"7:0", "7:1", "7:2"})

    index.add_node_to_index(7, "新首段", "新标题", user_id=4)
    rows = _rows(collection)
    assert set(rows) == {"7:0"}
    assert rows["7:0"]["document"] == "新首段"
    assert rows["7:0"]["metadata"]["title"] == "新标题"


@pytest.mark.parametrize("after", [False, True])
def test_empty_content_cleanup_failure_propagates_and_replay_converges(index, monkeypatch, after):
    index.add_node_to_index(7, "旧首段|旧尾段", user_id=4)
    collection = index._get_user_collection(4)
    before = _rows(collection)
    failing_collection = _FailOnceCollection(collection, "delete", after=after)
    monkeypatch.setattr(index, "_get_user_collection", lambda user_id: failing_collection)

    with pytest.raises(RuntimeError, match="injected delete failure"):
        index.add_node_to_index(7, "", user_id=4)
    assert _rows(collection) == ({} if after else before)

    index.add_node_to_index(7, "", user_id=4)
    assert _rows(collection) == {}
