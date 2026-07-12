"""Authentication and data-isolation tests for public API boundaries."""

import json

from app.models.relationship import Relationship
from app.models.user import User
from app.services.agent_tools import execute_tool
from tests.conftest import create_node, register_user


def test_protected_endpoint_rejects_missing_bearer_token(client):
    response = client.get("/api/nodes", headers={"Authorization": ""})

    assert response.status_code == 401


def test_second_user_cannot_read_owner_node_through_api_or_agent_tool(client, db):
    node = create_node(client, title="owner-only", content="private")
    token = register_user(client, username="second-user")

    response = client.get(
        f"/api/nodes/{node['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404

    second_user = db.query(User).filter(User.username == "second-user").one()
    result = execute_tool(
        "get_node_details",
        {"node_id": node["id"]},
        db,
        user_id=second_user.id,
    )

    assert "not found" in result.lower()


def test_user_cannot_create_relationship_to_another_users_node(client):
    owner_node = create_node(client, title="owner-only")
    second_token = register_user(client, username="relationship-user")
    second_headers = {"Authorization": f"Bearer {second_token}"}
    second_node = client.post(
        "/api/nodes",
        json={"title": "second-only", "content": "private"},
        headers=second_headers,
    ).json()

    response = client.post(
        "/api/relationships",
        json={"source_id": second_node["id"], "target_id": owner_node["id"]},
        headers=second_headers,
    )

    assert response.status_code == 404


def test_agent_ignores_legacy_cross_user_relationship(client, db):
    owner_node = create_node(client, title="owner-only")
    second_token = register_user(client, username="legacy-relationship-user")
    second_headers = {"Authorization": f"Bearer {second_token}"}
    second_node = client.post(
        "/api/nodes",
        json={"title": "second-only", "content": "private"},
        headers=second_headers,
    ).json()
    owner = db.query(User).filter(User.username == "test-user").one()
    db.add(
        Relationship(
            user_id=owner.id,
            source_id=owner_node["id"],
            target_id=second_node["id"],
        )
    )
    db.commit()

    result = execute_tool(
        "get_node_details",
        {"node_id": owner_node["id"]},
        db,
        user_id=owner.id,
    )

    data = json.loads(result)
    assert data["relationships"] == []
    assert "second-only" not in result
