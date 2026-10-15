from datetime import datetime, timedelta

from app.models.index_job import IndexJob
from app.services.index_jobs import claim, complete, enqueue, fail, retry

NOW = datetime(2026, 10, 14)


def test_enqueue_is_part_of_callers_transaction(db):
    enqueue(db, 1, 42, "upsert", "a", now=NOW)
    db.rollback()
    assert db.get(IndexJob, (1, 42)) is None
    enqueue(db, 1, 42, "upsert", "a", now=NOW)
    db.commit()
    assert db.get(IndexJob, (1, 42)).state == "pending"


def test_new_generation_cannot_be_completed_by_old_lease(db):
    enqueue(db, 1, 42, "upsert", "a", now=NOW)
    db.commit()
    old = claim(db, now=NOW)
    db.commit()
    enqueue(db, 1, 42, "delete", "", now=NOW)
    db.commit()
    assert not complete(db, old, now=NOW)
    db.commit()
    job = db.get(IndexJob, (1, 42))
    assert (job.generation, job.operation, job.state) == (2, "delete", "pending")


def test_expired_lease_can_be_reclaimed_and_old_worker_rejected(db):
    enqueue(db, 1, 42, "upsert", "a", now=NOW)
    db.commit()
    first = claim(db, now=NOW, lease_seconds=5)
    db.commit()
    assert claim(db, now=NOW) is None
    assert not complete(db, first, now=NOW + timedelta(seconds=5))
    second = claim(db, now=NOW + timedelta(seconds=6))
    db.commit()
    assert second.lease_token != first.lease_token
    assert not complete(db, first, now=NOW + timedelta(seconds=6))
    assert complete(db, second, now=NOW + timedelta(seconds=7))


def test_failure_is_bounded_and_manually_retryable(db):
    enqueue(db, 1, 42, "upsert", "a", now=NOW)
    db.commit()
    first = claim(db, now=NOW)
    assert fail(db, first, "ValueError", now=NOW, max_attempts=2)
    db.commit()
    assert claim(db, now=NOW) is None
    second = claim(db, now=NOW + timedelta(minutes=10))
    assert fail(db, second, "RuntimeError", now=NOW + timedelta(minutes=10), max_attempts=2)
    db.commit()
    assert db.get(IndexJob, (1, 42)).state == "failed"
    assert not retry(db, 2, 42, now=NOW)
    assert retry(db, 1, 42, now=NOW)
    db.commit()
    assert claim(db, now=NOW).attempts == 1


def test_repeated_worker_crashes_eventually_require_manual_retry(db):
    enqueue(db, 1, 42, "delete", "", now=NOW)
    db.commit()
    for attempt in range(5):
        assert claim(db, now=NOW + timedelta(seconds=attempt * 10), lease_seconds=5)
        db.commit()
    assert claim(db, now=NOW + timedelta(minutes=10)) is None
    db.commit()
    assert db.get(IndexJob, (1, 42)).state == "failed"
