"""Tests for /api/tags endpoints."""
from tests.conftest import create_tag, create_node


class TestCreateTag:
    def test_basic_create(self, client):
        tag = create_tag(client, name="python", color="#3776ab")
        assert tag["name"] == "python"
        assert tag["color"] == "#3776ab"
        assert tag["is_ai_generated"] is False
        assert tag["node_count"] == 0

    def test_default_color(self, client):
        tag = create_tag(client, name="test")
        assert tag["color"] == "#6366f1"

    def test_duplicate_name_rejected(self, client):
        create_tag(client, name="unique")
        resp = client.post("/api/tags", json={"name": "unique"})
        assert resp.status_code == 409


class TestListTags:
    def test_empty(self, client):
        assert client.get("/api/tags").json() == []

    def test_with_node_count(self, client):
        create_tag(client, name="go")
        create_node(client, tags=["go"])
        create_node(client, tags=["go"])
        tags = client.get("/api/tags").json()
        go_tag = next(t for t in tags if t["name"] == "go")
        assert go_tag["node_count"] == 2


class TestDeleteTag:
    def test_delete_existing(self, client):
        tag = create_tag(client, name="temp")
        resp = client.delete(f"/api/tags/{tag['id']}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Should be gone
        tags = client.get("/api/tags").json()
        assert not any(t["name"] == "temp" for t in tags)

    def test_delete_nonexistent(self, client):
        resp = client.delete("/api/tags/99999")
        assert resp.status_code == 404