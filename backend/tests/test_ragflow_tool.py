"""自定义 Agent 的检索工具必须保留 RAGFlow 预核验凭据。"""

import json

from app.config import settings
from app.services import agent_tools


def test_ragflow_search_tool_preserves_verified_fingerprint(db, monkeypatch):
    monkeypatch.setattr(settings, "kb_retrieval_backend", "ragflow")
    monkeypatch.setattr(
        "app.services.ragflow_client.get_ragflow_client", lambda *a, **kw: object(),
    )

    def fake_retrieve(db_, *, user_id, query, top_k, client):
        return [{
            "node_id": 1, "title": "t", "content": "# t\n\nbody",
            "source_fingerprint": "fp", "evidence_verified": True,
            "distance": 0.1, "note_date": "", "date_source": "",
            "kb_latest_date": "",
        }]

    monkeypatch.setattr(
        "app.services.ragflow_retrieval.retrieve_for_user", fake_retrieve,
    )

    rows = json.loads(agent_tools._handle_search({"query": "q"}, db, user_id=1))

    assert rows[0]["evidence_verified"] is True
    assert rows[0]["source_fingerprint"] == "fp"
    assert rows[0]["node_id"] == 1