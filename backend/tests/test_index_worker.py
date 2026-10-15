
import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.index_job import IndexJob
from app.models.node import KnowledgeNode
from app.services.index_jobs import enqueue, fingerprint
from app.services.index_worker import run_once, writer_lock


def test_restart_replays_committed_job_from_current_sql(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'jobs.db'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    with sessions() as db:
        db.add(KnowledgeNode(id=42, user_id=1, title="current", content="body"))
        enqueue(db, 1, 42, "upsert", fingerprint("current", "body"))
        db.commit()
    calls = []
    def upsert(*args):
        calls.append(args)
    assert run_once(sessions, upsert, lambda *args: None) == "succeeded"
    assert calls == [(42, "body", "current", 1)]
    assert run_once(sessions, upsert, lambda *args: None) == "idle"
    with sessions() as db:
        assert db.get(IndexJob, (1, 42)).state == "succeeded"
    engine.dispose()


def test_failed_delete_is_visible_and_does_not_succeed(db):
    from tests.conftest import TestSession

    enqueue(db, 1, 42, "delete", "")
    db.commit()
    def broken(*args):
        raise OSError("private secret/path")
    assert run_once(TestSession, broken, broken) == "pending"
    db.expire_all()
    job = db.get(IndexJob, (1, 42))
    assert job.last_error_type == "OSError"
    assert job.attempts == 1


def test_only_one_writer_per_directory(tmp_path):
    with writer_lock(tmp_path), pytest.raises(RuntimeError, match="writer"), writer_lock(tmp_path):
        pass
    with writer_lock(tmp_path):
        pass


def test_alembic_new_table_on_temporary_database(tmp_path):
    from pathlib import Path

    from alembic.config import Config

    from alembic import command

    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    config.attributes["database_url"] = url
    command.upgrade(config, "head")
    engine = create_engine(url)
    assert "index_jobs" in inspect(engine).get_table_names()
    assert {"generation", "lease_token", "source_fingerprint"} <= {
        column["name"] for column in inspect(engine).get_columns("index_jobs")
    }
    engine.dispose()
