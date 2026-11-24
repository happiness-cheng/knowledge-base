"""RAGFlow HTTP 客户端契约：信封、错误、上传/解析/检索流。"""

import json
from types import SimpleNamespace

import httpx
import pytest

from app.services.ragflow_client import (
    RagflowAPIError,
    RagflowClient,
    RagflowHTTPError,
    RagflowResponseError,
    get_ragflow_client,
    reset_ragflow_client,
)


def make_client(handler):
    return RagflowClient(
        "http://ragflow.test", "test-key", timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )


def test_create_dataset_sends_expected_body_and_returns_id():
    seen = {}

    def handler(request):
        seen["path"] = request.url.path
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"code": 0, "data": {"id": "ds-1", "name": "kb_user_1"}})

    with make_client(handler) as client:
        dataset = client.create_dataset("kb_user_1", language="Chinese")

    assert dataset["id"] == "ds-1"
    assert seen["path"] == "/api/v1/datasets"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["name"] == "kb_user_1"
    assert seen["body"]["parse_type"] == 1
    assert seen["body"]["parser_id"] == "general"


def test_ensure_dataset_reuses_existing_name_before_creating():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json={"code": 0, "data": [
                {"id": "ds-existing", "name": "kb_user_1"},
            ]})
        raise AssertionError("must not create when dataset exists")

    with make_client(handler) as client:
        dataset = client.ensure_dataset("kb_user_1")

    assert dataset["id"] == "ds-existing"
    assert calls == [("GET", "/api/v1/datasets")]


def test_upload_update_parse_list_delete_and_retrieve_flow():
    calls = []

    def handler(request):
        calls.append((request.method, request.url.path, request.content))
        path = request.url.path
        if request.method == "POST" and path == "/api/v1/datasets/ds-1/documents":
            assert request.headers["content-type"].startswith("multipart/form-data")
            assert b"node-7.md" in request.content
            return httpx.Response(200, json={"code": 0, "data": [
                {"id": "doc-1", "name": "node-7.md", "run": "UNSTART"},
            ]})
        if request.method == "PATCH":
            assert json.loads(request.content) == {
                "meta_fields": {"node_id": "7", "source_fingerprint": "fp"},
            }
            return httpx.Response(200, json={"code": 0})
        if request.method == "POST" and path == "/api/v1/datasets/ds-1/chunks":
            assert json.loads(request.content) == {"document_ids": ["doc-1"]}
            return httpx.Response(200, json={"code": 0})
        if request.method == "GET" and path == "/api/v1/datasets/ds-1/documents":
            return httpx.Response(200, json={"code": 0, "data": {
                "docs": [{"id": "doc-1", "name": "node-7.md", "run": "DONE"}],
            }})
        if request.method == "DELETE":
            assert json.loads(request.content) == {"ids": ["doc-1"]}
            return httpx.Response(200, json={"code": 0})
        if request.method == "POST" and path == "/api/v1/retrieval":
            body = json.loads(request.content)
            assert body["dataset_ids"] == ["ds-1"]
            assert body["question"] == "q"
            return httpx.Response(200, json={"code": 0, "data": {"chunks": [
                {"id": "c1", "document_id": "doc-1", "content": "evidence",
                 "similarity": 0.9, "vector_similarity": 0.8, "term_similarity": 0.7},
            ]}})
        raise AssertionError(f"unexpected request {request.method} {path}")

    with make_client(handler) as client:
        uploaded = client.upload_document("ds-1", "node-7.md", b"# note")
        assert uploaded["id"] == "doc-1"
        client.update_document_metadata("ds-1", "doc-1", {
            "node_id": "7", "source_fingerprint": "fp",
        })
        client.parse_documents("ds-1", ["doc-1"])
        docs = client.list_documents("ds-1")
        assert docs[0]["run"] == "DONE"
        client.delete_documents("ds-1", ["doc-1"])
        chunks = client.retrieve("q", ["ds-1"], page_size=5)

    assert chunks[0]["document_id"] == "doc-1"
    assert len(calls) == 6


def test_list_documents_paginates_until_short_page():
    pages = []

    def handler(request):
        page = int(request.url.params.get("page", "1"))
        pages.append(page)
        rows = [{"id": f"doc-{page}-{i}"} for i in range(100 if page == 1 else 1)]
        return httpx.Response(200, json={"code": 0, "data": {"docs": rows}})

    with make_client(handler) as client:
        docs = client.list_documents("ds-1")

    assert len(docs) == 101
    assert pages == [1, 2]


def test_business_error_code_raises_without_leaking_key():
    def handler(request):
        return httpx.Response(200, json={"code": 102, "message": "bad dataset"})

    with make_client(handler) as client:
        with pytest.raises(RagflowAPIError) as caught:
            client.create_dataset("kb_user_1")

    assert caught.value.code == 102
    assert "test-key" not in str(caught.value)


def test_http_error_raises_without_leaking_key():
    def handler(request):
        return httpx.Response(401, json={"code": 109, "message": "auth failed"})

    with make_client(handler) as client:
        with pytest.raises(RagflowHTTPError) as caught:
            client.create_dataset("kb_user_1")

    assert caught.value.status_code == 401
    assert "test-key" not in str(caught.value)


def test_non_json_and_malformed_payload_are_rejected():
    def non_json(request):
        return httpx.Response(200, text="not json")

    with make_client(non_json) as client:
        with pytest.raises(RagflowResponseError):
            client.create_dataset("kb_user_1")

    def malformed(request):
        return httpx.Response(200, json={"code": 0, "data": {}})

    with make_client(malformed) as client:
        with pytest.raises(RagflowResponseError):
            client.create_dataset("kb_user_1")


def test_health_accepts_plain_health_payload():
    def handler(request):
        return httpx.Response(200, json={"db": "ok", "status": "ok"})

    with make_client(handler) as client:
        assert client.health() is True


def test_health_returns_false_on_transport_error():
    def handler(request):
        raise httpx.ConnectError("down")

    with make_client(handler) as client:
        assert client.health() is False


def test_get_ragflow_client_returns_none_without_config():
    reset_ragflow_client()
    settings = SimpleNamespace(
        ragflow_base_url="", ragflow_api_key="", ragflow_timeout_seconds=30,
    )
    assert get_ragflow_client(settings) is None


def test_get_ragflow_client_reuses_and_resets_singleton():
    reset_ragflow_client()
    settings = SimpleNamespace(
        ragflow_base_url="http://ragflow.test", ragflow_api_key="test-key",
        ragflow_timeout_seconds=5,
    )
    first = get_ragflow_client(settings)
    second = get_ragflow_client(settings)
    assert first is second
    reset_ragflow_client()
    third = get_ragflow_client(settings)
    assert third is not first
    reset_ragflow_client()