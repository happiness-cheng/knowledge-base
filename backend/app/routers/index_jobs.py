from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.database import get_db
from app.models.index_job import IndexJob
from app.models.user import User
from app.services.index_jobs import retry

router = APIRouter(prefix="/index-jobs", tags=["index-jobs"])


@router.get("/{node_id}")
def status(node_id: int, db: Annotated[Session, Depends(get_db)], user: Annotated[User, Depends(get_current_user)]):
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
