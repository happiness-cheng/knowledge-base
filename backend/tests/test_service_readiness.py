from unittest.mock import Mock

import pytest
from sqlalchemy import text

from app import main
from app.services import rag_service


def test_readiness_checks_actual_dependencies(client, monkeypatch):
    heartbeat = Mock(return_value=1)
    monkeypatch.setattr(rag_service.chroma_client, "heartbeat", heartbeat)
    assert client.get("/api/health").json()["status"] == "ok"
    response = client.get("/api/ready")
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    heartbeat.assert_called_once()


def test_index_failure_is_sanitized_and_not_liveness_failure(client, monkeypatch):
    monkeypatch.setattr(rag_service.chroma_client, "heartbeat", Mock(side_effect=OSError("secret-token")))
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert "secret-token" not in response.text
    assert response.json()["checks"]["index"] == "unavailable"
    assert client.get("/api/health").status_code == 200


@pytest.mark.parametrize("table", ["index_jobs", "knowledge_nodes", "users"])
def test_missing_required_schema_returns_not_ready(client, db, table):
    db.execute(text(f"DROP TABLE {table}"))
    db.commit()
    response = client.get("/api/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["sql"] == "unavailable"


@pytest.mark.parametrize("path", ["/%2e%2e/private.txt", "/..%5cprivate.txt"])
def test_frontend_cannot_escape_dist(client, tmp_path, monkeypatch, path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("frontend", encoding="utf-8")
    (tmp_path / "private.txt").write_text("PRIVATE", encoding="utf-8")
    monkeypatch.setattr(main, "DIST_DIR", dist)
    response = client.get(path)
    assert response.status_code == 404
    assert "PRIVATE" not in response.text


def test_frontend_rejects_symlink_escape(client, tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    private = tmp_path / "private.txt"
    private.write_text("PRIVATE", encoding="utf-8")
    try:
        (dist / "link.txt").symlink_to(private)
    except OSError:
        pytest.skip("Windows 当前权限不支持创建符号链接")
    monkeypatch.setattr(main, "DIST_DIR", dist)
    assert client.get("/link.txt").status_code == 404


def test_frontend_explicit_path_matches_container_layout(tmp_path, monkeypatch):
    monkeypatch.setenv("KB_FRONTEND_DIST", str(tmp_path))
    assert main.resolve_frontend_dist() == tmp_path
