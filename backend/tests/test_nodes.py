"""Tests for /api/nodes endpoints."""
from tests.conftest import create_node, create_tag


class TestCreateNode:
    def test_basic_create(self, client):
        node = create_node(client, title="FastAPI 教程", content="FastAPI 是一个现代 Python web 框架")
        assert node["title"] == "FastAPI 教程"
        assert node["content"] == "FastAPI 是一个现代 Python web 框架"
        assert node["id"] > 0
        assert node["importance"] == 0.5
        assert node["ai_analyzed"] is False

    def test_create_with_tags(self, client):
        node = create_node(client, tags=["python", "web"])
        assert node["tags"] == ["python", "web"]

    def test_create_with_category(self, client):
        node = create_node(client, category="编程")
        assert node["category"] == "编程"

    def test_create_auto_creates_tags(self, client):
        """Creating a node with new tag names should auto-create those tags."""
        create_node(client, tags=["newtag1"])
        tags = client.get("/api/tags").json()
        tag_names = [t["name"] for t in tags]
        assert "newtag1" in tag_names

    def test_create_reuses_existing_tags(self, client):
        """If a tag already exists, it should be reused, not duplicated."""
        create_tag(client, name="python")
        create_node(client, tags=["python"])
        tags = client.get("/api/tags").json()
        python_tags = [t for t in tags if t["name"] == "python"]
        assert len(python_tags) == 1


class TestListNode:
    def test_empty_list(self, client):
        resp = client.get("/api/nodes")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_summaries(self, client):
        create_node(client, title="N1", content="C1")
        create_node(client, title="N2", content="C2")
        nodes = client.get("/api/nodes").json()
        assert len(nodes) == 2
        # Summary should not include content
        for n in nodes:
            assert "content" not in n
            assert "title" in n

    def test_filter_by_tag(self, client):
        create_node(client, title="A", tags=["go"])
        create_node(client, title="B", tags=["python"])
        nodes = client.get("/api/nodes", params={"tag": "go"}).json()
        assert len(nodes) == 1
        assert nodes[0]["title"] == "A"

    def test_filter_by_category(self, client):
        create_node(client, title="A", category="后端")
        create_node(client, title="B", category="前端")
        nodes = client.get("/api/nodes", params={"category": "前端"}).json()
        assert len(nodes) == 1
        assert nodes[0]["title"] == "B"

    def test_search(self, client):
        create_node(client, title="Django 笔记", content="Django 是 Python 框架")
        create_node(client, title="React 笔记", content="React 是前端库")
        nodes = client.get("/api/nodes", params={"search": "Django"}).json()
        assert len(nodes) == 1
        assert nodes[0]["title"] == "Django 笔记"

    def test_pagination(self, client):
        for i in range(5):
            create_node(client, title=f"Node {i}")
        nodes = client.get("/api/nodes", params={"limit": 2, "offset": 0}).json()
        assert len(nodes) == 2


class TestGetNode:
    def test_get_existing(self, client):
        created = create_node(client, title="Test", content="Body")
        node = client.get(f"/api/nodes/{created['id']}").json()
        assert node["title"] == "Test"
        assert node["content"] == "Body"
        # Detail should include extra fields
        assert "created_at" in node
        assert "updated_at" in node

    def test_get_not_found(self, client):
        resp = client.get("/api/nodes/99999")
        assert resp.status_code == 404


class TestUpdateNode:
    def test_update_title(self, client):
        node = create_node(client, title="Old")
        resp = client.put(f"/api/nodes/{node['id']}", json={"title": "New"})
        assert resp.status_code == 200
        assert resp.json()["title"] == "New"

    def test_update_content_resets_ai_analyzed(self, client):
        node = create_node(client)
        resp = client.put(f"/api/nodes/{node['id']}", json={"content": "Updated content"})
        assert resp.json()["ai_analyzed"] is False

    def test_update_tags(self, client):
        node = create_node(client, tags=["old_tag"])
        resp = client.put(f"/api/nodes/{node['id']}", json={"tags": ["new_tag"]})
        assert resp.json()["tags"] == ["new_tag"]

    def test_update_not_found(self, client):
        resp = client.put("/api/nodes/99999", json={"title": "X"})
        assert resp.status_code == 404

    def test_partial_update(self, client):
        """Only provided fields should change."""
        node = create_node(client, title="Keep", content="Also keep")
        resp = client.put(f"/api/nodes/{node['id']}", json={"category": "新分类"})
        data = resp.json()
        assert data["title"] == "Keep"
        assert data["content"] == "Also keep"
        assert data["category"] == "新分类"


class TestDeleteNode:
    def test_delete_existing(self, client):
        node = create_node(client)
        resp = client.delete(f"/api/nodes/{node['id']}")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Verify it's gone
        assert client.get(f"/api/nodes/{node['id']}").status_code == 404

    def test_delete_not_found(self, client):
        resp = client.delete("/api/nodes/99999")
        assert resp.status_code == 404

    def test_delete_node_with_tags(self, client):
        """Deleting a node should not fail even if it has tags."""
        node = create_node(client, tags=["tag_a", "tag_b"])
        resp = client.delete(f"/api/nodes/{node['id']}")
        assert resp.status_code == 200
        # Tags should still exist (orphan cleanup is optional)
        tags = client.get("/api/tags").json()
        tag_names = [t["name"] for t in tags]
        assert "tag_a" in tag_names

    def test_delete_node_with_relationships(self, client):
        """Deleting a node should also remove its relationships."""
        from tests.conftest import create_relationship
        n1 = create_node(client, title="A")
        n2 = create_node(client, title="B")
        create_relationship(client, n1["id"], n2["id"])
        # Delete n1 — relationship should be cleaned up
        resp = client.delete(f"/api/nodes/{n1['id']}")
        assert resp.status_code == 200
        rels = client.get("/api/relationships").json()
        assert len(rels) == 0

    def test_delete_node_with_both_direction_relationships(self, client):
        """Deleting a node should remove relationships in both directions."""
        from tests.conftest import create_relationship
        n1 = create_node(client, title="A")
        n2 = create_node(client, title="B")
        n3 = create_node(client, title="C")
        create_relationship(client, n1["id"], n2["id"])  # n1 -> n2
        create_relationship(client, n3["id"], n2["id"])  # n3 -> n2
        # Delete n2 — both relationships should be cleaned up
        resp = client.delete(f"/api/nodes/{n2['id']}")
        assert resp.status_code == 200
        rels = client.get("/api/relationships").json()
        assert len(rels) == 0

    def test_delete_then_verify_graph(self, client):
        """After delete, graph should not contain the node or its links."""
        from tests.conftest import create_relationship
        n1 = create_node(client)
        n2 = create_node(client)
        create_relationship(client, n1["id"], n2["id"])
        client.delete(f"/api/nodes/{n1['id']}")
        graph = client.get("/api/graph").json()
        node_ids = [n["id"] for n in graph["nodes"]]
        assert n1["id"] not in node_ids
        assert len(graph["links"]) == 0