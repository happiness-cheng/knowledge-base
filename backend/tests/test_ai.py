"""Tests for /api/ai endpoints."""
from unittest.mock import patch, MagicMock


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