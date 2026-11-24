"""对运行中的 RAGFlow 做一次真实冒烟：建库→上传→解析→检索→清理。

需要显式配置：
  KB_RETRIEVAL_BACKEND=ragflow
  RAGFLOW_BASE_URL=http://127.0.0.1:9380
  RAGFLOW_API_KEY=...
在 backend 目录运行：
  python -m scripts.ragflow_smoke
"""

import argparse
import json
import time
from uuid import uuid4

from app.config import Settings
from app.services.ragflow_client import RagflowClient, RagflowError
from app.services.ragflow_sync import STATE_FAILED, STATE_READY, document_state


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--question", default="RAGFlow smoke test")
    parser.add_argument("--keywords-similarity-weight", type=float, default=0.3,
                        help="冒烟默认偏向量；生产默认仍是 RAGFlow 的 0.7")
    parser.add_argument("--keep", action="store_true", help="保留数据集用于手工检查")
    args = parser.parse_args(argv)
    settings = Settings()
    if not settings.ragflow_base_url or not settings.ragflow_api_key:
        print(json.dumps({"status": "not_configured",
                          "hint": "set RAGFLOW_BASE_URL and RAGFLOW_API_KEY"}))
        return 2

    token = uuid4().hex[:10]
    dataset_id = ""
    document_id = ""
    client = RagflowClient(
        settings.ragflow_base_url, settings.ragflow_api_key,
        timeout_seconds=settings.ragflow_timeout_seconds,
    )
    try:
        if not client.health():
            print(json.dumps({"status": "unhealthy",
                              "base_url": settings.ragflow_base_url}))
            return 1
        dataset = client.create_dataset(
            f"kb_smoke_{token}", embedding_model=settings.ragflow_embedding_model,
        )
        dataset_id = dataset["id"]
        document = client.upload_document(
            dataset_id, f"smoke-{token}.md",
            f"# Smoke {token}\n\nRAGFlow integration smoke token: {token}\n".encode(),
        )
        document_id = document["id"]
        client.update_document_metadata(dataset_id, document_id, {
            "node_id": "smoke",
            "source_fingerprint": token,
            "title": f"Smoke {token}",
        })
        client.parse_documents(dataset_id, [document_id])

        deadline = time.monotonic() + max(args.timeout, 1.0)
        state = "pending"
        error = None
        while time.monotonic() < deadline:
            docs = client.list_documents(dataset_id, document_id=document_id)
            if not docs:
                state, error = "missing", "document_missing"
            else:
                state, error = document_state(docs[0])
            if state in {STATE_READY, STATE_FAILED}:
                break
            time.sleep(2)
        if state != STATE_READY:
            print(json.dumps({"status": "parse_failed" if state == STATE_FAILED
                              else "parse_not_done", "state": state,
                              "error": error, "dataset_id": dataset_id,
                              "document_id": document_id}))
            return 1

        chunks = client.retrieve(
            args.question, [dataset_id], page_size=5,
            keywords_similarity_weight=args.keywords_similarity_weight,
        )
        print(json.dumps({
            "status": "ok",
            "dataset_id": dataset_id,
            "document_id": document_id,
            "chunks": len(chunks),
            "top_chunk": chunks[0] if chunks else None,
        }, ensure_ascii=False))
        return 0
    except RagflowError as exc:
        print(json.dumps({"status": "error", "error": type(exc).__name__,
                          "message": str(exc)[:300]}))
        return 1
    finally:
        if not args.keep and dataset_id:
            try:
                if document_id:
                    client.delete_documents(dataset_id, [document_id])
                client.delete_datasets([dataset_id])
            except RagflowError:
                pass
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())