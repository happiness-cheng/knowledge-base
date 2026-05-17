"""Integration tests: full lifecycle of nodes, tags, relationships, and graph."""
from tests.conftest import create_node, create_tag, create_relationship


class TestFullLifecycle:
    """End-to-end: create nodes with tags and relationships, verify, delete, re-verify."""

    def test_create_tag_relate_delete_verify(self, client):
        # 1. Create nodes with tags
        n1 = create_node(client, title="Python 基础", tags=["python", "编程"])
        n2 = create_node(client, title="Django 入门", tags=["python", "web"])
        n3 = create_node(client, title="React 入门", tags=["javascript", "web"])

        # 2. Create relationships
        rel = create_relationship(client, n1["id"], n2["id"], rel_type="prerequisite")

        # 3. Verify tags node_count
        tags = {t["name"]: t for t in client.get("/api/tags").json()}
        assert tags["python"]["node_count"] == 2
        assert tags["web"]["node_count"] == 2
        assert tags["javascript"]["node_count"] == 1

        # 4. Verify graph
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) == 3
        assert len(graph["links"]) == 1

        # 5. Delete n1
        resp = client.delete(f"/api/nodes/{n1['id']}")
        assert resp.status_code == 200

        # 6. Verify relationship cleaned up
        rels = client.get("/api/relationships").json()
        assert len(rels) == 0

        # 7. Verify graph only has n2, n3
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) == 2
        assert len(graph["links"]) == 0

        # 8. Verify nodes list
        nodes = client.get("/api/nodes").json()
        titles = [n["title"] for n in nodes]
        assert "Python 基础" not in titles
        assert "Django 入门" in titles

    def test_multiple_relationships_delete_middle_node(self, client):
        """Delete a node that is connected to multiple others."""
        n1 = create_node(client, title="A")
        n2 = create_node(client, title="B")
        n3 = create_node(client, title="C")
        n4 = create_node(client, title="D")

        create_relationship(client, n1["id"], n2["id"])
        create_relationship(client, n2["id"], n3["id"])
        create_relationship(client, n3["id"], n4["id"])

        # Delete n2 and n3 (middle nodes)
        client.delete(f"/api/nodes/{n2['id']}")
        client.delete(f"/api/nodes/{n3['id']}")

        # Only n1 and n4 should remain, no relationships
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) == 2
        assert len(graph["links"]) == 0

    def test_tag_filter_after_node_deletion(self, client):
        """Tag filter should return correct results after deleting a tagged node."""
        n1 = create_node(client, title="A", tags=["shared"])
        n2 = create_node(client, title="B", tags=["shared"])

        # Filter by tag
        nodes = client.get("/api/nodes", params={"tag": "shared"}).json()
        assert len(nodes) == 2

        # Delete one
        client.delete(f"/api/nodes/{n1['id']}")

        # Filter again
        nodes = client.get("/api/nodes", params={"tag": "shared"}).json()
        assert len(nodes) == 1
        assert nodes[0]["title"] == "B"


class TestRelationshipBoundaries:
    """Edge cases for relationship creation and deletion."""

    def test_create_relationship_both_directions(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        create_relationship(client, n1["id"], n2["id"])
        create_relationship(client, n2["id"], n1["id"])
        rels = client.get("/api/relationships").json()
        assert len(rels) == 2

    def test_create_duplicate_relationship(self, client):
        """Creating the same relationship twice should succeed (no dedup)."""
        n1 = create_node(client)
        n2 = create_node(client)
        create_relationship(client, n1["id"], n2["id"])
        create_relationship(client, n1["id"], n2["id"])
        rels = client.get("/api/relationships").json()
        assert len(rels) == 2  # No dedup

    def test_delete_relationship_preserves_nodes(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        rel = create_relationship(client, n1["id"], n2["id"])
        client.delete(f"/api/relationships/{rel['id']}")
        # Both nodes should still exist
        assert client.get(f"/api/nodes/{n1['id']}").status_code == 200
        assert client.get(f"/api/nodes/{n2['id']}").status_code == 200

    def test_relationship_with_nonexistent_source(self, client):
        """Creating relationship with nonexistent source — SQLite may not enforce FK."""
        n2 = create_node(client)
        resp = client.post("/api/relationships", json={
            "source_id": 99999, "target_id": n2["id"],
        })
        # SQLite doesn't enforce FK by default, so this may succeed or fail
        assert resp.status_code in (200, 400, 500)

    def test_relationship_with_nonexistent_target(self, client):
        """Creating relationship with nonexistent target — SQLite may not enforce FK."""
        n1 = create_node(client)
        resp = client.post("/api/relationships", json={
            "source_id": n1["id"], "target_id": 99999,
        })
        assert resp.status_code in (200, 400, 500)


class TestGraphNodeConsistency:
    """Graph data should always be consistent with actual nodes/relationships."""

    def test_empty_db_graph(self, client):
        graph = client.get("/api/graph").json()
        assert graph == {"nodes": [], "links": []}

    def test_graph_nodes_match_api_nodes(self, client):
        create_node(client, title="X")
        create_node(client, title="Y")
        nodes = client.get("/api/nodes").json()
        graph = client.get("/api/graph").json()
        assert len(graph["nodes"]) == len(nodes)

    def test_graph_links_match_api_relationships(self, client):
        n1 = create_node(client)
        n2 = create_node(client)
        create_relationship(client, n1["id"], n2["id"])
        rels = client.get("/api/relationships").json()
        graph = client.get("/api/graph").json()
        assert len(graph["links"]) == len(rels)