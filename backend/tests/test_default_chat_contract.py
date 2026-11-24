"""默认链路契约：默认 LC 严格 RAG + dense；昂贵候选必须显式开启。"""

import pytest
from pydantic import ValidationError

from app.routers.chat import MessageCreate


def test_default_request_uses_langchain_strict_rag_without_optional_models():
    default = MessageCreate(content="q")
    assert default.backend == "langchain"
    assert default.kb_only is True
    assert default.retrieval_mode == "current"
    assert default.rerank is False
    assert default.rewrite is False


def test_optional_candidates_must_be_explicit():
    candidate = MessageCreate(
        content="q", retrieval_mode="hybrid", rerank=True, rewrite=True,
    )
    assert candidate.backend == "langchain"
    assert candidate.retrieval_mode == "hybrid"
    assert candidate.rerank is True
    assert candidate.rewrite is True


def test_custom_agent_defaults_to_current_and_disables_candidates():
    agent = MessageCreate(content="q", kb_only=False)
    assert agent.backend == "custom"
    assert agent.retrieval_mode == "current"
    assert agent.rerank is False
    assert agent.rewrite is False


def test_ai_search_defaults_to_custom_agent_without_kb():
    general = MessageCreate(content="q", ai_search=True)
    assert general.backend == "custom"
    assert general.kb_only is False


@pytest.mark.parametrize("payload", [
    {"content": "q", "kb_only": True, "ai_search": True},
    {"content": "q", "backend": "langchain", "kb_only": False},
    {"content": "q", "rerank": True},
    {"content": "q", "rewrite_bindings": {"它": "HTTP2"}},
    {"content": "q", "backend": "custom", "retrieval_mode": "hybrid"},
    {"content": "q", "backend": "custom", "rerank": True},
    {"content": "q", "backend": "custom", "rewrite": True},
])
def test_invalid_combinations_are_rejected(payload):
    with pytest.raises(ValidationError):
        MessageCreate(**payload)