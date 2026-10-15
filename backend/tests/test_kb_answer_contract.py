"""通过真实 Agent 入口验证严格 KB 回答边界，不调用外部模型。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.models.node import KnowledgeNode
from app.services.agent_service import run_agent


def run_strict(db, monkeypatch, payload, results=None):
    client = MagicMock()
    text = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    response = SimpleNamespace(content=[SimpleNamespace(text=text)])
    if results is not None:
        tool = SimpleNamespace(type="tool_use", name="search_knowledge_base",
                               input={"query": "q"}, id="search-1")
        client.chat_with_tools.side_effect = [SimpleNamespace(content=[tool]), response]
        monkeypatch.setattr("app.services.agent_service.execute_tool",
                            lambda *a, **kw: json.dumps(results))
    else:
        client.chat_with_tools.return_value = response
    result = run_agent(db, SimpleNamespace(messages=[]), "只回答笔记", user_id=3,
                       ai_client=client, kb_only=True)
    return result, client


def test_missing_evidence_is_fixed_refusal_without_background(db, monkeypatch):
    result, _ = run_strict(db, monkeypatch, {
        "status": "not_found", "answer": "建议 WAIT [doc:7]，RPO约1ms",
        "source_ids": [7],
    }, results=[])
    assert result["answer_status"] == "not_found"
    assert result["content"] == "NOT_FOUND_IN_KB: 本次检索未找到支持该问题的证据。"
    assert result["source_ids"] == []
    assert result["found_in_kb"] is False
    assert result["steps"][-1]["content"] == result["content"]


def test_supported_answer_requires_retrieved_owned_evidence(db, monkeypatch):
    db.add(KnowledgeNode(id=7, user_id=3, title="HTTP2", content="多路复用"))
    db.commit()
    result, client = run_strict(db, monkeypatch, {
        "status": "supported", "answer": "笔记记载多路复用 [doc:7]",
        "source_ids": [7],
    }, results=[{"node_id": 7, "content": "多路复用"}])
    assert result["answer_status"] == "supported"
    assert result["source_ids"] == [7]
    assert result["found_in_kb"] is True
    assert {t["name"] for t in client.chat_with_tools.call_args.kwargs["tools"]} == {
        "search_knowledge_base", "get_node_details",
    }


@pytest.mark.parametrize("returned,owner", [(False, 3), (True, 4)])
def test_unretrieved_or_foreign_citation_fails_closed(db, monkeypatch, returned, owner):
    db.add(KnowledgeNode(id=7, user_id=owner, title="private", content="secret"))
    db.commit()
    result, _ = run_strict(db, monkeypatch, {
        "status": "supported", "answer": "secret [doc:7]", "source_ids": [7],
    }, results=[{"node_id": 7, "content": "secret"}] if returned else [])
    assert result["answer_status"] == "error"
    assert result["source_ids"] == []
    assert "secret" not in result["content"]


@pytest.mark.parametrize("payload", [
    "not JSON", [], {"status": "maybe", "answer": "a", "source_ids": []},
    {"status": "supported", "answer": "unsupported", "source_ids": []},
    {"status": "supported", "answer": "a [doc:8]", "source_ids": [7]},
    {"status": "supported", "answer": "a [doc:7]", "source_ids": [True]},
])
def test_invalid_contract_is_error_not_absence(db, monkeypatch, payload):
    result, _ = run_strict(db, monkeypatch, payload, results=[])
    assert result["answer_status"] == "error"
    assert result["found_in_kb"] is False
    assert "NOT_FOUND_IN_KB" not in result["content"]


def test_provider_failure_is_error_without_general_fallback(db):
    client = MagicMock()
    client.chat_with_tools.side_effect = RuntimeError("private provider detail")
    result = run_agent(db, SimpleNamespace(messages=[]), "q", user_id=3,
                       ai_client=client, kb_only=True)
    assert result["answer_status"] == "error"
    assert "private provider detail" not in result["content"]
    client.chat.assert_not_called()


def test_general_mode_remains_plain_text(db):
    client = MagicMock()
    client.chat.return_value = "通用补充"
    result = run_agent(db, SimpleNamespace(messages=[]), "请补充通用知识",
                       ai_client=client, ai_search=True)
    assert result["content"] == "通用补充"
    client.chat_with_tools.assert_not_called()


def test_failed_retrieval_is_error_not_refusal(db, monkeypatch):
    result, _ = run_strict(db, monkeypatch, {
        "status": "not_found", "answer": "", "source_ids": [],
    }, results={"error": "search unavailable"})
    assert result["answer_status"] == "error"
    assert "NOT_FOUND_IN_KB" not in result["content"]


def test_foreign_evidence_is_not_sent_to_model(db, monkeypatch):
    db.add(KnowledgeNode(id=7, user_id=4, title="private", content="secret"))
    db.commit()
    result, client = run_strict(db, monkeypatch, {
        "status": "not_found", "answer": "", "source_ids": [],
    }, results=[{"node_id": 7, "content": "secret"}])
    assert result["answer_status"] == "not_found"
    messages = client.chat_with_tools.call_args.kwargs["messages"]
    assert messages[-1]["content"][0]["content"] == "[]"


def test_strict_mode_denies_unadvertised_web_tool(db, monkeypatch):
    client = MagicMock()
    client.chat_with_tools.return_value = SimpleNamespace(content=[SimpleNamespace(
        type="tool_use", name="web_search", input={"query": "secret"}, id="web-1",
    )])
    execute = MagicMock()
    monkeypatch.setattr("app.services.agent_service.execute_tool", execute)
    result = run_agent(db, SimpleNamespace(messages=[]), "q", ai_client=client, kb_only=True)
    assert result["answer_status"] == "error"
    execute.assert_not_called()


def test_strict_chat_api_passes_mode_and_returns_status(client, monkeypatch):
    conv = client.post("/api/chat/conversations", json={"title": "strict"}).json()
    captured = {}

    def fake_agent(*args, **kwargs):
        captured.update(kwargs)
        return {"content": "NOT_FOUND_IN_KB: 本次检索未找到支持该问题的证据。",
                "source_ids": [], "is_from_kb": False, "found_in_kb": False,
                "steps": [], "web_sources": [], "answer_status": "not_found"}

    monkeypatch.setattr("app.routers.chat.run_agent", fake_agent)
    response = client.post(f"/api/chat/conversations/{conv['id']}/messages",
                           json={"content": "q", "kb_only": True})
    assert response.status_code == 200
    assert captured["kb_only"] is True
    assert response.json()["answer_status"] == "not_found"
    # 无schema变更，历史读取不能臆造未持久化的状态。
    history = client.get(f"/api/chat/conversations/{conv['id']}").json()
    assert history["messages"][-1]["answer_status"] is None


def test_conflicting_chat_modes_are_rejected(client):
    conv = client.post("/api/chat/conversations", json={"title": "strict"}).json()
    response = client.post(f"/api/chat/conversations/{conv['id']}/messages",
                           json={"content": "q", "kb_only": True, "ai_search": True})
    assert response.status_code == 422
    assert client.get(f"/api/chat/conversations/{conv['id']}").json()["messages"] == []


def test_invalid_tool_arguments_are_error_without_execution(db, monkeypatch):
    client = MagicMock()
    client.chat_with_tools.return_value = SimpleNamespace(content=[SimpleNamespace(
        type="tool_use", name="get_node_details", input=[], id="bad-1",
    )])
    execute = MagicMock()
    monkeypatch.setattr("app.services.agent_service.execute_tool", execute)
    result = run_agent(db, SimpleNamespace(messages=[]), "q", ai_client=client, kb_only=True)
    assert result["answer_status"] == "error"
    execute.assert_not_called()


def test_database_validation_failure_is_error(monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError

    db = MagicMock()
    db.query.side_effect = SQLAlchemyError("private db detail")
    result, _ = run_strict(db, monkeypatch, {
        "status": "not_found", "answer": "", "source_ids": [],
    }, results=[{"node_id": 7, "content": "a"}])
    assert result["answer_status"] == "error"
    assert "private db detail" not in result["content"]


def test_strict_chat_api_uses_real_agent_contract(client, monkeypatch):
    """实际走路由、Agent和收口，仅替换外部模型及检索提供方。"""
    model = MagicMock()
    model.chat_with_tools.side_effect = [
        SimpleNamespace(content=[SimpleNamespace(type="tool_use",
            name="search_knowledge_base", input={"query": "RPO"}, id="t1")]),
        SimpleNamespace(content=[SimpleNamespace(text=json.dumps({
            "status": "not_found", "answer": "建议WAIT [doc:28]", "source_ids": [28],
        }))]),
    ]
    monkeypatch.setattr("app.routers.chat.get_client_for_user", lambda user: model)
    monkeypatch.setattr("app.services.agent_service.execute_tool", lambda *a, **kw: "[]")
    conv = client.post("/api/chat/conversations", json={"title": "RPO"}).json()
    response = client.post(f"/api/chat/conversations/{conv['id']}/messages", json={
        "content": "有没有RPO实测值？没有就说无法确认", "kb_only": True,
    })
    assert response.status_code == 200
    body = response.json()
    assert body["answer_status"] == "not_found"
    assert body["source_node_ids"] == []
    assert body["content"] == "NOT_FOUND_IN_KB: 本次检索未找到支持该问题的证据。"
    assert body["agent_steps"][-1]["content"] == body["content"]


def test_iteration_limit_fails_closed_without_an_extra_model_call(db, monkeypatch):
    monkeypatch.setattr("app.services.agent_service.MAX_ITERATIONS", 1)
    monkeypatch.setattr("app.services.agent_service.execute_tool", lambda *a, **kw: "[]")
    model = MagicMock()
    model.chat_with_tools.return_value = SimpleNamespace(content=[SimpleNamespace(
        type="tool_use", name="search_knowledge_base", input={"query": "q"}, id="t1",
    )])
    model.chat.return_value = json.dumps({"status": "not_found", "answer": "建议",
                                         "source_ids": []})
    result = run_agent(db, SimpleNamespace(messages=[]), "q", ai_client=model, kb_only=True)
    assert result["answer_status"] == "error"
    model.chat.assert_not_called()
    assert "建议" not in result["content"]
