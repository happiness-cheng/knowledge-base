"""Tests for /api/graph endpoints."""
from tests.conftest import create_node, create_relationship


class TestGetGraph:
    def test_empty_graph(self, client):
        data = client.get("/api/graph").json()
        assert data["nodes"] == []
        assert data["links"] == []

    def test_graph_with_nodes_and_links(self, client):
        n1 = create_node(client, title="A", category="cat1")
        n2 = create_node(client, title="B")
        create_relationship(client, n1["id"], n2["id"])
        data = client.get("/api/graph").json()
        assert len(data["nodes"]) == 2
        assert len(data["links"]) == 1
        assert data["links"][0]["source"] == n1["id"]
        assert data["links"][0]["target"] == n2["id"]


class TestSubgraph:
    def test_subgraph_single_node(self, client):
        n = create_node(client, title="Isolated")
        data = client.get(f"/api/graph/node/{n['id']}").json()
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["title"] == "Isolated"

    def test_subgraph_with_neighbors(self, client):
        n1 = create_node(client, title="Center")
        n2 = create_node(client, title="Neighbor")
        n3 = create_node(client, title="Unrelated")
        create_relationship(client, n1["id"], n2["id"])
        data = client.get(f"/api/graph/node/{n1['id']}").json()
        titles = {node["title"] for node in data["nodes"]}
        assert "Center" in titles
        assert "Neighbor" in titles
        assert "Unrelated" not in titles

    def test_subgraph_hops(self, client):
        n1 = create_node(client, title="A")
        n2 = create_node(client, title="B")
        n3 = create_node(client, title="C")
        create_relationship(client, n1["id"], n2["id"])
        create_relationship(client, n2["id"], n3["id"])
        # 1 hop from n1: only n1, n2
        data = client.get(f"/api/graph/node/{n1['id']}", params={"hops": 1}).json()
        titles = {node["title"] for node in data["nodes"]}
        assert titles == {"A", "B"}
        # 2 hops: n1, n2, n3
        data = client.get(f"/api/graph/node/{n1['id']}", params={"hops": 2}).json()
        titles = {node["title"] for node in data["nodes"]}
        assert titles == {"A", "B", "C"}