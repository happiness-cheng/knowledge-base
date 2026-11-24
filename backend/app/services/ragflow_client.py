"""RAGFlow HTTP 客户端：只依赖 httpx，不绑定 SDK 的 Python 版本。

RAGFlow 1.0 的 REST API 使用统一信封 `{"code": 0, "data": ...}`；HTTP 200 也可能
是业务错误。这里把 HTTP 错误、业务错误和形状错误分开抛出，调用方不需要解析
message 文本。API Key 只出现在 Authorization 头，不进入异常、日志或返回体。
"""

from __future__ import annotations

import json
from threading import Lock
from typing import Any

import httpx


class RagflowError(RuntimeError):
    """RAGFlow 调用的基类；消息已截断，不包含凭据。"""


class RagflowHTTPError(RagflowError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"RAGFlow HTTP {status_code}: {message[:300]}")


class RagflowAPIError(RagflowError):
    def __init__(self, code: int | str, message: str):
        self.code = code
        super().__init__(f"RAGFlow API {code}: {message[:300]}")


class RagflowResponseError(RagflowError):
    pass


class RagflowClient:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        if not base_url or not api_key:
            raise ValueError("RAGFlow base_url and api_key are required")
        if timeout_seconds <= 0:
            raise ValueError("RAGFlow timeout must be positive")
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout_seconds,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Accept": "application/json",
            },
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()

    def _payload(self, response: httpx.Response) -> dict:
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            raise RagflowResponseError(
                f"RAGFlow returned non-JSON response (HTTP {response.status_code})"
            ) from None
        if response.status_code >= 400:
            message = payload.get("message") if isinstance(payload, dict) else ""
            raise RagflowHTTPError(response.status_code, str(message or "request failed"))
        if not isinstance(payload, dict):
            raise RagflowResponseError("RAGFlow response must be a JSON object")
        code = payload.get("code")
        if code != 0:
            safe_code = code if isinstance(code, (int, str)) else "unknown"
            raise RagflowAPIError(safe_code, str(payload.get("message", "")))
        return payload

    def _request(self, method: str, path: str, **kwargs) -> dict:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise RagflowHTTPError(0, type(exc).__name__) from None
        return self._payload(response)

    def health(self) -> bool:
        try:
            response = self._client.get("/api/v1/system/healthz")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def create_dataset(self, name: str, *, language: str = "Chinese",
                       embedding_model: str = "") -> dict:
        body: dict[str, Any] = {
            "name": name,
            "language": language,
            "parse_type": 1,
            "parser_id": "general",
        }
        if embedding_model:
            body["embedding_model"] = embedding_model
        payload = self._request("POST", "/api/v1/datasets", json=body)
        data = payload.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise RagflowResponseError("RAGFlow create_dataset returned no dataset id")
        return data

    def list_datasets(self, *, name: str = "", page_size: int = 100) -> list[dict]:
        params: dict[str, Any] = {"page": 1, "page_size": page_size}
        if name:
            params["name"] = name
        payload = self._request("GET", "/api/v1/datasets", params=params)
        data = payload.get("data")
        if not isinstance(data, list):
            raise RagflowResponseError("RAGFlow list_datasets returned no list")
        return [item for item in data if isinstance(item, dict)]

    def ensure_dataset(self, name: str, **kwargs) -> dict:
        for item in self.list_datasets(name=name):
            if str(item.get("name", "")).casefold() == name.casefold():
                return item
        try:
            return self.create_dataset(name, **kwargs)
        except RagflowAPIError:
            # 并发创建时 RAGFlow 可能返回已存在；回读一次，仍失败则上抛。
            for item in self.list_datasets(name=name):
                if str(item.get("name", "")).casefold() == name.casefold():
                    return item
            raise

    def upload_document(self, dataset_id: str, filename: str, content: bytes,
                        *, mime_type: str = "text/markdown") -> dict:
        payload = self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/documents",
            files={"file": (filename, content, mime_type)},
        )
        data = payload.get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise RagflowResponseError("RAGFlow upload_document returned no document")
        if not isinstance(data[0].get("id"), str):
            raise RagflowResponseError("RAGFlow upload_document returned no document id")
        return data[0]

    def update_document_metadata(self, dataset_id: str, document_id: str,
                                 meta_fields: dict[str, str]) -> None:
        self._request(
            "PATCH",
            f"/api/v1/datasets/{dataset_id}/documents/{document_id}",
            json={"meta_fields": meta_fields},
        )

    def parse_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        if not document_ids:
            raise ValueError("document_ids must not be empty")
        self._request(
            "POST",
            f"/api/v1/datasets/{dataset_id}/chunks",
            json={"document_ids": document_ids},
        )

    def list_documents(self, dataset_id: str, *, document_id: str = "",
                       page_size: int = 100, max_pages: int = 100) -> list[dict]:
        if page_size < 1 or page_size > 100 or max_pages < 1:
            raise ValueError("invalid document pagination")
        documents: list[dict] = []
        for page in range(1, max_pages + 1):
            params: dict[str, Any] = {"page": page, "page_size": page_size}
            if document_id:
                params["id"] = document_id
            payload = self._request(
                "GET", f"/api/v1/datasets/{dataset_id}/documents", params=params,
            )
            data = payload.get("data")
            if isinstance(data, dict):
                batch = data.get("docs")
            else:
                batch = data
            if not isinstance(batch, list):
                raise RagflowResponseError("RAGFlow list_documents returned no docs list")
            rows = [item for item in batch if isinstance(item, dict)]
            documents.extend(rows)
            if document_id or len(rows) < page_size:
                break
        return documents

    def delete_documents(self, dataset_id: str, document_ids: list[str]) -> None:
        if not document_ids:
            return
        self._request(
            "DELETE",
            f"/api/v1/datasets/{dataset_id}/documents",
            json={"ids": document_ids},
        )

    def delete_datasets(self, dataset_ids: list[str]) -> None:
        if not dataset_ids:
            return
        self._request("DELETE", "/api/v1/datasets", json={"ids": dataset_ids})

    def retrieve(self, question: str, dataset_ids: list[str], *,
                 page_size: int = 20, similarity_threshold: float = 0.2,
                 keywords_similarity_weight: float = 0.7,
                 knn_top_k: int = 1024, rerank_id: str = "") -> list[dict]:
        if not question.strip() or not dataset_ids:
            raise ValueError("question and dataset_ids are required")
        body: dict[str, Any] = {
            "question": question,
            "dataset_ids": dataset_ids,
            "page": 1,
            "page_size": page_size,
            "similarity_threshold": similarity_threshold,
            "keywords_similarity_weight": keywords_similarity_weight,
            "knn_top_k": knn_top_k,
        }
        if rerank_id:
            body["rerank_id"] = rerank_id
        payload = self._request("POST", "/api/v1/retrieval", json=body)
        data = payload.get("data")
        chunks = data.get("chunks") if isinstance(data, dict) else None
        if not isinstance(chunks, list):
            raise RagflowResponseError("RAGFlow retrieval returned no chunks list")
        return [chunk for chunk in chunks if isinstance(chunk, dict)]


_client: RagflowClient | None = None
_client_key: tuple[str, str, float] | None = None
_client_lock = Lock()


def get_ragflow_client(settings_obj=None) -> RagflowClient | None:
    """按当前配置返回单例；未配置时返回 None，调用方决定降级/报错。"""
    global _client, _client_key
    if settings_obj is None:
        from app.config import settings as settings_obj
    key = (
        settings_obj.ragflow_base_url,
        settings_obj.ragflow_api_key,
        float(settings_obj.ragflow_timeout_seconds),
    )
    if not key[0] or not key[1]:
        return None
    with _client_lock:
        if _client is None or _client_key != key:
            if _client is not None:
                _client.close()
            _client = RagflowClient(
                key[0], key[1], timeout_seconds=key[2],
            )
            _client_key = key
        return _client


def reset_ragflow_client() -> None:
    """测试用：关闭并清除单例，避免跨用例复用连接或凭据。"""
    global _client, _client_key
    with _client_lock:
        if _client is not None:
            _client.close()
        _client = None
        _client_key = None