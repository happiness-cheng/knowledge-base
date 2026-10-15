"""评测 API 限额覆盖降级调用，未知用量不当作零费用。"""

from types import SimpleNamespace

import pytest


def test_tools_and_chat_share_request_budget_and_output_cap():
    from eval.api_client import BoundedAIClient, RequestBudgetExceeded
    requests = []
    response = SimpleNamespace(content=[SimpleNamespace(type='text', text='answer')],
        usage=SimpleNamespace(input_tokens=5, output_tokens=2, cache_read_input_tokens=3))
    sdk = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: requests.append(kw) or response))
    client = BoundedAIClient(sdk, 'fixture', max_requests=2, max_output_tokens=100)
    client.chat_with_tools(system='public', messages=[{'role': 'user', 'content': 'public'}], tools=[])
    assert client.chat(system='public', messages=[{'role': 'user', 'content': 'public'}]) == 'answer'
    with pytest.raises(RequestBudgetExceeded):
        client.chat(system='public', messages=[])
    assert len(requests) == 2
    assert all(row['max_tokens'] == 100 for row in requests)
    assert client.usage_totals == {'input_tokens': 16, 'output_tokens': 4}
    assert client.budget_exceeded


def test_failed_sdk_attempt_is_counted_without_recording_exception_secrets():
    from eval.api_client import BoundedAIClient, RequestBudgetExceeded
    def unavailable(**kwargs):
        raise TimeoutError('secret should never be in call ledger')
    client = BoundedAIClient(SimpleNamespace(messages=SimpleNamespace(create=unavailable)), 'fixture', max_requests=1)
    with pytest.raises(TimeoutError):
        client.chat_with_tools(system='public', messages=[], tools=[])
    with pytest.raises(RequestBudgetExceeded):
        client.chat(system='public', messages=[])
    assert len(client.calls) == 1
    assert client.calls[0]['error_type'] == 'TimeoutError'
    assert 'secret' not in str(client.calls)
    assert client.usage_totals is None


def test_tool_context_guard_excludes_unselected_nodes_and_relationship_titles():
    import json
    from eval.api_client import filter_tool_context
    raw = json.dumps([{'node_id': 7, 'content': 'selected'}, {'node_id': 16, 'content': 'account'}])
    assert json.loads(filter_tool_context('search_knowledge_base', raw, {7})) == [{'node_id': 7, 'content': 'selected'}]
    raw = json.dumps({'id': 7, 'content': 'selected', 'relationships': [
        {'other_node_id': 16, 'other_title': 'account'}, {'other_node_id': 8, 'other_title': 'unselected'}]})
    assert json.loads(filter_tool_context('get_node_details', raw, {7}))['relationships'] == []
    assert 'account' not in filter_tool_context('get_node_details', json.dumps({'id': 16, 'content': 'account'}), {7})
