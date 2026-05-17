"""Tests for /api/relationships endpoints."""
from tests.conftest import create_node, create_relationship


class TestCreateRelationship:
    def test_basic_create(self, client):
        n1 = create_node(client, title="Node A")
        n2 = create_node(client, title="Node B")
        rel = create_relationship(client, n1["id"], n2["id"])
        assert rel["source_id"] == n1["id"]
        assert rel["target_id"] == n2["id"]
        assert rel["rel_type"] == "related_to"
        assert rel["is_ai_generated"] is False

    def test_with_topics(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        rel = create_relationship(client, n1["id"], n2["id"],
                                  source_topic="Collector", target_topic="Queue")
        assert rel["source_topic"] == "Collector"
        assert rel["target_topic"] == "Queue"

    def test_without_topics(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        rel = create_relationship(client, n1["id"], n2["id"])
        assert rel["source_topic"] is None
        assert rel["target_topic"] is None


class TestListRelationships:
    def test_empty(self, client):
        assert client.get("/api/relationships").json() == []

    def test_list(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        create_relationship(client, n1["id"], n2["id"])
        rels = client.get("/api/relationships").json()
        assert len(rels) == 1


class TestDeleteRelationship:
    def test_delete_existing(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        rel = create_relationship(client, n1["id"], n2["id"])
        resp = client.delete(f"/api/relationships/{rel['id']}")
        assert resp.status_code == 200
        assert client.get("/api/relationships").json() == []

    def test_delete_not_found(self, client):
        resp = client.delete("/api/relationships/99999")
        assert resp.status_code == 404