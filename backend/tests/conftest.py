"""Shared test fixtures for all test modules."""
import sys
import os
from contextlib import asynccontextmanager
import pytest
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import app.database as db_module
from app.database import Base, get_db
from app.main import app

# In-memory SQLite for tests — StaticPool keeps one connection so :memory: is shared
TEST_ENGINE = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

@event.listens_for(TEST_ENGINE, "connect")
def _set_sqlite_nocase(dbapi_conn, connection_record):
    dbapi_conn.create_collation(
        "NOCASE", lambda a, b: (a.lower() > b.lower()) - (a.lower() < b.lower())
    )

TestSession = sessionmaker(bind=TEST_ENGINE)


@pytest.fixture(autouse=True)
def _patch_engine():
    """Replace the app-level engine + session so all routes hit the test DB."""
    orig_engine = db_module.engine
    orig_session = db_module.SessionLocal

    db_module.engine = TEST_ENGINE
    db_module.SessionLocal = TestSession

    Base.metadata.create_all(bind=TEST_ENGINE)
    yield
    Base.metadata.drop_all(bind=TEST_ENGINE)

    db_module.engine = orig_engine
    db_module.SessionLocal = orig_session


@pytest.fixture
def db():
    """Provide a fresh database session."""
    session = TestSession()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI test client with overridden DB and mocked external services."""

    def override_get_db():
        session = TestSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db

    # Mock external services
    patchers = [
        patch("app.services.rag_service.add_node_to_index"),
        patch("app.services.rag_service.remove_node_from_index"),
        patch("app.services.chat_service.generate_chat_response", return_value=("mock response", [])),
        patch("app.routers.nodes._safe_auto_analyze"),
    ]
    for p in patchers:
        p.start()

    claude_p = patch("app.services.claude_client.claude_client")
    mock_cc = claude_p.start()
    mock_cc.client = None

    # Replace lifespan with no-op
    @asynccontextmanager
    async def _noop_lifespan(app):
        yield
    app.router.lifespan_context = _noop_lifespan

    with TestClient(app) as c:
        yield c

    for p in patchers:
        p.stop()
    claude_p.stop()
    app.dependency_overrides.clear()


# ---------- helper shortcuts ----------

def create_node(client, title="Test Node", content="Some content", tags=None, category=None):
    payload = {"title": title, "content": content, "tags": tags or [], "category": category}
    resp = client.post("/api/nodes", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_tag(client, name="python", **kwargs):
    payload = {"name": name, **kwargs}
    resp = client.post("/api/tags", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def create_relationship(client, source_id, target_id, rel_type="related_to", **kwargs):
    payload = {
        "source_id": source_id, "target_id": target_id,
        "rel_type": rel_type, **kwargs,
    }
    resp = client.post("/api/relationships", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()