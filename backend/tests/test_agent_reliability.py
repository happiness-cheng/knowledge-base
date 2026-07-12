"""Deterministic reliability checks for the knowledge-base Agent."""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services import agent_service
from app.services.agent_tools import _handle_search


def test_agent_removes_citations_not_returned_by_tools(monkeypatch):
    tool = SimpleNamespace(
        type="tool_use",
        name="search_knowledge_base",
        input={"query": "q"},
        id="tool-1",
    )
    answer = SimpleNamespace(text="Allowed [doc:7]; fabricated [doc:999].")
    client = MagicMock()
    client.chat_with_tools.side_effect = [
        SimpleNamespace(content=[tool]),
        SimpleNamespace(content=[answer]),
    ]
    monkeypatch.setattr(
        agent_service,
        "execute_tool",
        lambda *args, **kwargs: json.dumps([{"node_id": 7}]),
    )

    result = agent_service.run_agent(
        MagicMock(),
        SimpleNamespace(messages=[]),
        "q",
        user_id=3,
        ai_client=client,
    )

    assert result["source_ids"] == [7]
    assert "[doc:7]" in result["content"]
    assert "[doc:999]" not in result["content"]


def test_search_tool_clamps_negative_result_count(monkeypatch):
    received = {}
    monkeypatch.setattr(
        "app.services.agent_tools.retrieve_relevant_nodes",
        lambda query, top_k, user_id: received.update(top_k=top_k, user_id=user_id)
        or [],
    )

    _handle_search({"query": "safe", "top_k": -5}, MagicMock(), user_id=12)

    assert received == {"top_k": 1, "user_id": 12}


def test_agent_prompt_marks_tool_text_as_untrusted():
    assert "UNTRUSTED CONTENT SAFETY" in agent_service.AGENT_SYSTEM_PROMPT
    assert "must never override" in agent_service.AGENT_SYSTEM_PROMPT
