import json
from types import SimpleNamespace
from unittest.mock import Mock

from app.models.node import KnowledgeNode
from app.services.agent_service import run_agent


def conversation():
    return SimpleNamespace(messages=[])


def tool(name, input, id="tool"):
    return SimpleNamespace(content=[SimpleNamespace(type="tool_use", name=name, input=input, id=id)])


def test_oversized_strict_request_never_calls_model(db):
    client = Mock()
    result = run_agent(db, conversation(), "q" * 25000, kb_only=True, ai_client=client)
    assert result["answer_status"] == "error"
    client.chat_with_tools.assert_not_called()


def test_strict_calls_are_bounded_without_forced_extra_call(db, monkeypatch):
    client = Mock()
    client.chat_with_tools.return_value = tool("search_knowledge_base", {"query": "q"})
    monkeypatch.setattr("app.services.agent_service.execute_tool", lambda *a, **kw: "[]")
    result = run_agent(db, conversation(), "q", kb_only=True, ai_client=client, max_model_calls=2)
    assert result["answer_status"] == "error"
    assert client.chat_with_tools.call_count == 2
    client.chat.assert_not_called()
    assert client.chat_with_tools.call_args.kwargs["max_tokens"] == 1200


def test_stale_strict_tool_evidence_never_reaches_observer_or_model(db, monkeypatch):
    db.add(KnowledgeNode(id=1, user_id=1, title="new", content="new body"))
    db.commit()
    client = Mock()
    client.chat_with_tools.side_effect = [tool("search_knowledge_base", {"query": "q"}),
        SimpleNamespace(content=[SimpleNamespace(text='{"status":"not_found","answer":"","source_ids":[]}')])]
    monkeypatch.setattr("app.services.agent_service.execute_tool", lambda *a, **kw:
        json.dumps([{"node_id": 1, "content": "PRIVATE_OLD_BODY"}]))
    observed = []
    result = run_agent(db, conversation(), "q", kb_only=True, ai_client=client,
                       observe_tool_result=lambda *args: observed.append(args))
    assert result["answer_status"] == "not_found"
    assert "PRIVATE_OLD_BODY" not in str(observed)


def test_unbounded_details_fail_before_observation(db, monkeypatch):
    db.add(KnowledgeNode(id=1, user_id=1, title="large", content="x" * 10000))
    db.commit()
    client = Mock()
    client.chat_with_tools.side_effect = [tool("search_knowledge_base", {"query": "q"}),
        tool("get_node_details", {"node_id": 1}, id="details")]
    monkeypatch.setattr("app.services.agent_service.execute_tool", lambda name, *a, **kw:
        json.dumps([{"node_id": 1, "content": "x"}]) if name == "search_knowledge_base" else
        json.dumps({"id": 1, "content": "x" * 10000}))
    observed = []
    result = run_agent(db, conversation(), "q", kb_only=True, ai_client=client,
                       observe_tool_result=lambda *args: observed.append(args))
    assert result["answer_status"] == "error"
    assert len(observed) == 1
