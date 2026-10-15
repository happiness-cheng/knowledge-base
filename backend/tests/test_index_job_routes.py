import pytest

from app.models.index_job import IndexJob
from tests.conftest import create_node, register_user


def test_node_lifecycle_persists_jobs(client, db):
    node = create_node(client)
    job = db.query(IndexJob).filter_by(node_id=node["id"]).one()
    assert (job.generation, job.operation) == (1, "upsert")
    response = client.put(f'/api/nodes/{node["id"]}', json={"title": "new title", "content": ""})
    assert response.status_code == 200
    db.expire_all()
    assert job.generation == 2
    assert client.delete(f'/api/nodes/{node["id"]}').status_code == 200
    db.expire_all()
    assert (job.generation, job.operation) == (3, "delete")


@pytest.mark.parametrize("endpoint", ["text", "file", "batch", "chat"])
def test_import_and_saved_answer_persist_jobs(client, db, endpoint):
    if endpoint == "text":
        response = client.post("/api/import/text", json={"title": "a", "content": "b"})
    elif endpoint == "chat":
        response = client.post("/api/chat/save-to-kb", json={"title": "a", "content": "b", "question": "q"})
    else:
        response = client.post(f"/api/import/{endpoint}", files={
            "file" if endpoint == "file" else "files": ("note.txt", b"text", "text/plain")
        })
    assert response.status_code == 200, response.text
    assert db.query(IndexJob).count() > 0


def test_status_and_retry_are_owner_scoped(client, db):
    node = create_node(client)
    job = db.query(IndexJob).filter_by(node_id=node["id"]).one()
    assert client.get(f'/api/index-jobs/{node["id"]}').json()["state"] == "pending"
    job.state = "failed"
    db.commit()
    token = register_user(client, username="another-owner")
    original = client.headers["Authorization"]
    client.headers["Authorization"] = f"Bearer {token}"
    assert client.get(f'/api/index-jobs/{node["id"]}').status_code == 404
    assert client.post(f'/api/index-jobs/{node["id"]}/retry').status_code == 404
    client.headers["Authorization"] = original
    assert client.post(f'/api/index-jobs/{node["id"]}/retry').status_code == 200
