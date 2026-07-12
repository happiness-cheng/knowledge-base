"""Tests for /api/ai endpoints."""
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

from cryptography.fernet import Fernet

from app.models.user import User
from app.services.secret_store import SecretCipher


class TestAISettings:
    def test_get_settings(self, client):
        resp = client.get("/api/ai/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert "ai_base_url" in data
        assert "ai_model_name" in data
        assert "has_api_key" in data


class TestAnalyzeNode:
    def test_analyze_not_found(self, client):
        resp = client.post("/api/ai/analyze-node/99999")
        assert resp.status_code == 404

    def test_analyze_node(self, client):
        # Create a node first
        node = client.post("/api/nodes", json={
            "title": "Python 学习笔记",
            "content": "Python 是一门编程语言",
        }).json()

        # Mock the AI extraction (patch where it's imported in the router)
        with patch("app.routers.ai.extract_knowledge") as mock_extract:
            mock_extract.return_value = {
                "summary": "Python 学习笔记",
                "category": "编程",
                "importance": 0.8,
                "tags": ["python", "编程"],
            }
            resp = client.post(f"/api/ai/analyze-node/{node['id']}")

        assert resp.status_code == 200
        data = resp.json()
        assert data["summary"] == "Python 学习笔记"
        assert data["importance"] == 0.8


class TestFindRelationships:
    def test_too_few_nodes(self, client):
        create_resp = client.post("/api/nodes", json={"title": "Only one", "content": "x"})
        node_id = create_resp.json()["id"]
        # Need to mark as ai_analyzed for the default query
        resp = client.post("/api/ai/find-relationships", json=[node_id])
        assert resp.status_code == 200
        assert resp.json()["suggestions"] == []


def test_save_settings_persists_ciphertext(client, db, monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.secret_store.settings.ai_key_encryption_key", key)

    response = client.post("/api/ai/settings", json={"ai_api_key": "sk-user-secret"})

    assert response.status_code == 200
    user = db.query(User).filter(User.username == "test-user").one()
    assert user.ai_api_key.startswith("fernet:v1:")
    assert "sk-user-secret" not in user.ai_api_key


def test_get_client_for_user_decrypts_before_provider_call(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setattr("app.services.secret_store.settings.ai_key_encryption_key", key)
    user = SimpleNamespace(
        ai_api_key=SecretCipher(key).encrypt("sk-user-secret"),
        ai_base_url="https://provider.example/v1",
        ai_model_name="model-name",
    )

    with patch("app.services.claude_client.anthropic.Anthropic") as provider:
        from app.services.claude_client import get_client_for_user

        get_client_for_user(user)

    assert provider.call_args.kwargs["api_key"] == "sk-user-secret"


def test_save_settings_rejects_missing_encryption_key(client, monkeypatch):
    monkeypatch.setattr("app.services.secret_store.settings.ai_key_encryption_key", "")

    response = client.post("/api/ai/settings", json={"ai_api_key": "sk-user-secret"})

    assert response.status_code == 503
