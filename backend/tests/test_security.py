"""Authentication and data-isolation tests for public API boundaries."""

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
