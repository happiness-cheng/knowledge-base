"""Run the frozen 36-case retrieval set through a real RAGFlow backend.

Creates a temporary in-memory SQL mapping and a unique RAGFlow dataset, uploads
the 16 frozen corpus documents, waits for parsing, runs retrieval, computes the
same metrics as `eval.run_retrieval_regression`, then cleans the dataset up.

This measures real RAGFlow retrieval (given the configured embedding model); it
does not measure answer generation.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

import app.models  # noqa: F401 -- register every model before create_all
from app.models.user import User  # noqa: F401 -- users table for KnowledgeNode FK
from app.config import Settings
from app.database import Base
from app.models.node import KnowledgeNode
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.services.ragflow_client import RagflowClient
from app.services.ragflow_retrieval import retrieve_for_user
from app.services.ragflow_sync import document_state, refresh_states, sync_node
from eval.benchmark import file_hash
from eval.core_corpus import load_manifest_corpus, validate_core_dataset
from eval.retrieval_regression import evaluate_case, summarize

BACKEND = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND.parent
MANIFEST = BACKEND / "eval/fixtures/core-rag-corpus-20261013.json"
DATASET = BACKEND / "eval/fixtures/core-rag-20261013.json"
ACTIVE_STATES = {"pending", "uploaded", "parsing"}


def _manifest_titles() -> dict[int, str]:
    raw = json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        int(row["node_id"]): str(row.get("title") or f"note-{row['node_id']}")
        for row in raw.get("documents", []) if "node_id" in row
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        default=BACKEND / "eval/reports/ragflow-retrieval.json")
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--keywords-weight", type=float, default=0.3)
    parser.add_argument("--similarity-threshold", type=float, default=0.2)
    parser.add_argument("--reuse-dataset", default="",
                        help="复用已解析的 dataset id；跳过上传/解析")
    parser.add_argument("--timeout", type=float, default=900.0)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error(f"refusing to overwrite {args.output}")

    settings = Settings()
    if not settings.ragflow_base_url or not settings.ragflow_api_key:
        parser.error("RAGFLOW_BASE_URL and RAGFLOW_API_KEY are required")
    if not settings.ragflow_embedding_model:
        parser.error("RAGFLOW_EMBEDDING_MODEL is required for a real quality run")

    corpus = load_manifest_corpus(MANIFEST, REPO_ROOT)
    titles = _manifest_titles()
    cases = validate_core_dataset(DATASET, corpus)
    metadata = json.loads(DATASET.read_text(encoding="utf-8")).get("case_metadata", {})
    token = uuid4().hex[:10]
    prefix = f"kb_rag_{token}"
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    client = RagflowClient(
        settings.ragflow_base_url, settings.ragflow_api_key,
        timeout_seconds=settings.ragflow_timeout_seconds,
    )
    report: dict = {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "backend": "ragflow",
        "top_k": args.top_k,
        "embedding_model": settings.ragflow_embedding_model,
        "keywords_similarity_weight": args.keywords_weight,
        "similarity_threshold": args.similarity_threshold,
        "dataset_sha256": file_hash(DATASET),
        "manifest_sha256": file_hash(MANIFEST),
        "retrieval_quality_measured": True,
        "model_quality_measured": False,
    }
    dataset_id = ""
    try:
        if not client.health():
            print(json.dumps({"status": "unhealthy"}))
            return 1
        with Session(engine) as db:
            for node_id, content in corpus.items():
                db.add(KnowledgeNode(
                    id=node_id, user_id=1,
                    title=titles.get(node_id, f"note-{node_id}"),
                    content=content,
                ))
            db.commit()
            if args.reuse_dataset:
                dataset_id = args.reuse_dataset
                db.add(RagflowDataset(
                    user_id=1, dataset_id=dataset_id,
                    name=f"reuse_{dataset_id[:8]}", embedding_model=settings.ragflow_embedding_model,
                ))
                for doc in client.list_documents(dataset_id, page_size=100):
                    meta = doc.get("meta_fields") or {}
                    try:
                        node_id = int(meta.get("node_id"))
                    except (TypeError, ValueError):
                        continue
                    fp = meta.get("source_fingerprint")
                    if node_id not in corpus or not isinstance(fp, str):
                        continue
                    state, _ = document_state(doc)
                    db.add(RagflowDocument(
                        user_id=1, node_id=node_id,
                        document_id=str(doc.get("id") or ""),
                        source_fingerprint=fp, state=state,
                    ))
                db.commit()
            else:
                nodes = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == 1).all()
                for node in nodes:
                    sync_node(
                        db, node, client, prefix=prefix,
                        embedding_model=settings.ragflow_embedding_model,
                    )
                db.commit()
                dataset = db.get(RagflowDataset, 1)
                dataset_id = dataset.dataset_id if dataset else ""
                deadline = time.monotonic() + max(args.timeout, 1.0)
                while time.monotonic() < deadline:
                    refresh_states(db, 1, client)
                    db.commit()
                    active = db.query(RagflowDocument).filter(
                        RagflowDocument.user_id == 1,
                        RagflowDocument.state.in_(ACTIVE_STATES),
                    ).count()
                    if active == 0:
                        break
                    time.sleep(3)
            states = {
                state: db.query(RagflowDocument).filter(
                    RagflowDocument.user_id == 1, RagflowDocument.state == state,
                ).count()
                for state in ("ready", "failed", "missing", "parsing", "pending", "uploaded")
            }
            records = []
            for case in cases:
                started = time.perf_counter()
                rows = retrieve_for_user(
                    db, user_id=1, query=case.question, top_k=args.top_k, client=client,
                    keywords_similarity_weight=args.keywords_weight,
                    similarity_threshold=args.similarity_threshold,
                )
                latency = (time.perf_counter() - started) * 1000
                records.append(evaluate_case(case, rows, latency_ms=latency))
            report["document_states"] = states
            report["summary"] = summarize(cases, records, case_metadata=metadata)
            report["cases"] = records
            report["dataset_id"] = dataset_id
    finally:
        client.close()
        if not args.keep and not args.reuse_dataset and dataset_id:
            cleanup = RagflowClient(
                settings.ragflow_base_url, settings.ragflow_api_key,
                timeout_seconds=settings.ragflow_timeout_seconds,
            )
            try:
                cleanup.delete_datasets([dataset_id])
            except Exception as exc:  # noqa: BLE001 - cleanup must not hide result
                report["cleanup_error"] = type(exc).__name__
            finally:
                cleanup.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print(json.dumps({
        "status": "ok", "output": str(args.output),
        "metrics": report.get("summary", {}).get("metrics"),
        "states": report.get("document_states"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())