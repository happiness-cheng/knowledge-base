from collections import Counter
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.index_job import IndexJob
from app.models.ragflow import RagflowDataset, RagflowDocument
from app.models.user import User
from app.services.index_jobs import retry

router = APIRouter(prefix="/index-jobs", tags=["index-jobs"])


@router.get("/status")
def index_status(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    probe_health: bool = False,
):
    """用户级索引健康视图；不扫描全量集合，不在默认路径调用远端。"""
    counts = dict(
        db.query(IndexJob.state, func.count())
        .filter(IndexJob.user_id == user.id)
        .group_by(IndexJob.state)
        .all()
    )
    jobs = {state: int(counts.get(state, 0)) for state in (
        "pending", "running", "failed", "succeeded",
    )}
    failed = (
        db.query(IndexJob)
        .filter(IndexJob.user_id == user.id, IndexJob.state == "failed")
        .order_by(IndexJob.updated_at.desc())
        .limit(20)
        .all()
    )
    result = {
        "backend": settings.kb_retrieval_backend,
        "jobs": jobs,
        "failed_jobs": [
            {"node_id": job.node_id, "generation": job.generation,
             "attempts": job.attempts, "last_error_type": job.last_error_type,
             "updated_at": job.updated_at}
            for job in failed
        ],
    }
    if settings.kb_retrieval_backend == "ragflow":
        dataset = db.get(RagflowDataset, user.id)
        docs = db.query(RagflowDocument).filter(
            RagflowDocument.user_id == user.id,
        ).all()
        doc_counts = Counter(doc.state for doc in docs)
        failed_docs = [
            {"node_id": doc.node_id, "state": doc.state,
             "last_error": doc.last_error, "updated_at": doc.updated_at}
            for doc in docs if doc.state in {"failed", "missing"}
        ][:20]
        health = None
        if probe_health:
            from app.services.ragflow_client import get_ragflow_client
            client = get_ragflow_client(settings)
            health = bool(client and client.health())
        result["ragflow"] = {
            "configured": bool(settings.ragflow_base_url and settings.ragflow_api_key),
            "dataset_id": dataset.dataset_id if dataset else None,
            "documents": dict(doc_counts),
            "failed_documents": failed_docs,
            "health": health,
        }
    else:
        from app.services import rag_service
        from app.services.index_metadata import metadata_status
        collection = rag_service._get_existing_user_collection(user.id)
        result["chroma"] = {
            "collection": collection.name if collection is not None else None,
            "count": collection.count() if collection is not None else 0,
            "metadata": metadata_status(collection.metadata) if collection is not None else
            metadata_status(None),
        }
    return result


@router.post("/reconcile")
def reconcile(
    db: Annotated[Session, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    apply: bool = False,
):
    if settings.kb_retrieval_backend != "ragflow":
        raise HTTPException(400, "reconcile is only available for the RAGFlow backend")
    from app.services.ragflow_reconcile import (
        apply_user_ragflow_repair, reconcile_user_ragflow,
    )

    report = reconcile_user_ragflow(db, user.id)
    if apply:
        report["enqueued"] = apply_user_ragflow_repair(db, report)
        db.commit()
    return report


@router.get("/{node_id}")
def job_status(node_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    job = db.get(IndexJob, (user.id, node_id))
    if job is None:
        raise HTTPException(404, "Index job not found")
    return {"node_id": job.node_id, "generation": job.generation,
            "operation": job.operation, "state": job.state, "attempts": job.attempts,
            "last_error_type": job.last_error_type, "updated_at": job.updated_at}


@router.post("/{node_id}/retry")
def retry_job(node_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
    if db.get(IndexJob, (user.id, node_id)) is None:
        raise HTTPException(404, "Index job not found")
    if not retry(db, user.id, node_id):
        raise HTTPException(409, "Only failed jobs can be retried")
    db.commit()
    return {"ok": True}
