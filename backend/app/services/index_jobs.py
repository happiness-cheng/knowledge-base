"""事务登记和 CAS 租约。函数不提交事务，由调用方决定提交/回滚。"""
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

from sqlalchemy import and_, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session
from sqlalchemy.sql.dml import Update

from app.models.index_job import IndexJob


def fingerprint(title: str, content: str) -> str:
    return hashlib.sha256(json.dumps([title, content], ensure_ascii=False).encode()).hexdigest()


def utc_now() -> datetime:
    # SQLite/MySQL DateTime 统一存无时区的 UTC，避免方言转换后的比较歧义。
    return datetime.now(UTC).replace(tzinfo=None)


def _affected(db: Session, statement: Update) -> int:
    return cast(CursorResult, db.execute(statement)).rowcount


def enqueue(db: Session, user_id: int, node_id: int, operation: str,
            source_fingerprint: str, *, now: datetime | None = None) -> None:
    if operation not in {"upsert", "delete"}:
        raise ValueError("invalid index operation")
    now = now or utc_now()
    db.flush()
    values = {"operation": operation, "state": "pending", "source_fingerprint": source_fingerprint,
              "attempts": 0, "next_attempt_at": now, "lease_token": None, "lease_until": None,
              "last_error_type": None, "updated_at": now}
    changed = _affected(db, update(IndexJob).where(
        IndexJob.user_id == user_id, IndexJob.node_id == node_id,
    ).values(generation=IndexJob.generation + 1, **values))
    if not changed:
        db.add(IndexJob(user_id=user_id, node_id=node_id, generation=1, **values))
    db.flush()


@dataclass(frozen=True)
class Lease:
    user_id: int
    node_id: int
    generation: int
    operation: str
    source_fingerprint: str
    attempts: int
    lease_token: str


def _eligible(now: datetime):
    return or_(and_(IndexJob.state == "pending", IndexJob.next_attempt_at <= now),
               and_(IndexJob.state == "running", IndexJob.lease_until <= now))


def claim(db: Session, *, now: datetime | None = None, lease_seconds: int = 300) -> Lease | None:
    now = now or utc_now()
    if lease_seconds <= 0:
        raise ValueError("lease must be positive")
    job = db.scalars(select(IndexJob).where(_eligible(now)).order_by(
        IndexJob.next_attempt_at, IndexJob.user_id, IndexJob.node_id).limit(1)).first()
    if job is None:
        return None
    if job.attempts >= 5:
        db.execute(update(IndexJob).where(
            IndexJob.user_id == job.user_id, IndexJob.node_id == job.node_id,
            IndexJob.generation == job.generation, _eligible(now),
        ).values(state="failed", lease_token=None, lease_until=None,
                 last_error_type="LeaseExpired", updated_at=now))
        return None
    token = uuid4().hex
    generation, attempts = job.generation, job.attempts + 1
    changed = _affected(db, update(IndexJob).where(
        IndexJob.user_id == job.user_id, IndexJob.node_id == job.node_id,
        IndexJob.generation == generation, _eligible(now),
    ).values(state="running", attempts=attempts, lease_token=token,
             lease_until=now + timedelta(seconds=lease_seconds), updated_at=now))
    if not changed:
        return None
    return Lease(job.user_id, job.node_id, generation, job.operation,
                 job.source_fingerprint, attempts, token)


def _owned(lease: Lease, now: datetime):
    return and_(IndexJob.user_id == lease.user_id, IndexJob.node_id == lease.node_id,
                IndexJob.generation == lease.generation, IndexJob.state == "running",
                IndexJob.lease_token == lease.lease_token, IndexJob.lease_until > now)


def complete(db: Session, lease: Lease, *, now: datetime | None = None) -> bool:
    now = now or utc_now()
    return bool(_affected(db, update(IndexJob).where(_owned(lease, now)).values(
        state="succeeded", lease_token=None, lease_until=None,
        last_error_type=None, updated_at=now)))


def fail(db: Session, lease: Lease, error_type: str, *, now: datetime | None = None,
         max_attempts: int = 5) -> bool:
    now = now or utc_now()
    return bool(_affected(db, update(IndexJob).where(_owned(lease, now)).values(
        state="failed" if lease.attempts >= max_attempts else "pending",
        lease_token=None, lease_until=None, last_error_type=error_type[:80],
        next_attempt_at=now + timedelta(seconds=min(300, 2 ** min(lease.attempts, 8))),
        updated_at=now)))


def retry(db: Session, user_id: int, node_id: int, *, now: datetime | None = None) -> bool:
    now = now or utc_now()
    return bool(_affected(db, update(IndexJob).where(
        IndexJob.user_id == user_id, IndexJob.node_id == node_id,
        IndexJob.state == "failed",
    ).values(state="pending", attempts=0, next_attempt_at=now,
             last_error_type=None, updated_at=now)))
