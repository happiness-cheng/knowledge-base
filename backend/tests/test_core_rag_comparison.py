"""有限在线准备入口的离线验收：纯计划与物理 transport 限额。"""

import json
import subprocess
import sys
from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from eval.run_core_rag_comparison import (
    CASE_IDS,
    HttpBudget,
    RequestBlocked,
    build_dry_plan,
)


def test_dry_plan_validates_frozen_development_cases_without_app_import():
    plan = build_dry_plan()
    assert tuple(case['case_id'] for case in plan['cases']) == CASE_IDS
    assert all(case['split'] == 'development' for case in plan['cases'])
    assert plan['physical_request_limit'] == 25
    assert plan['human_fact_review'] == 'pending'
    assert plan['online_assembly_ready'] is True


def test_dry_script_runs_from_any_cwd_without_loading_application(tmp_path):
    from eval import run_core_rag_comparison
    script = run_core_rag_comparison.__file__
    result = subprocess.run([sys.executable, '-X', 'utf8', script], cwd=tmp_path,
                            capture_output=True, text=True, encoding='utf-8', check=False)
    assert result.returncode == 0
    plan = json.loads(result.stdout)
    assert plan['mode'] == 'dry_run' and plan['physical_requests'] == 0
    code = "import sys; from eval.run_core_rag_comparison import build_dry_plan; build_dry_plan(); assert not any(x=='app' or x.startswith('app.') for x in sys.modules)"
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, check=False)
    assert result.returncode == 0


def test_physical_http_guard_blocks_before_send_and_counts_failed_sdk_request_once():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(503, json={'type': 'error', 'error': {
            'type': 'overloaded_error', 'message': 'offline failure',
        }})
    guard = HttpBudget(httpx.MockTransport(respond), max_requests=1)
    sdk = anthropic.Anthropic(api_key='PRIVATE_FIXTURE_CREDENTIAL', max_retries=0,
        http_client=httpx.Client(transport=guard))
    try:
        with guard.scope('CR02', 'strict_agent'):
            with pytest.raises(anthropic.APIStatusError):
                sdk.messages.create(model='fixture', max_tokens=600,
                                    messages=[{'role': 'user', 'content': 'public fixture'}])
            with pytest.raises(RequestBlocked):
                guard.handle_request(httpx.Request('POST', 'https://fixture.invalid', json={
                    'model': 'fixture', 'max_tokens': 600, 'messages': [],
                }))
        assert len(calls) == guard.physical_requests == 1
        assert guard.halted is True
        assert guard.usage_totals is None
        assert 'PRIVATE_FIXTURE_CREDENTIAL' not in json.dumps(guard.records)
    finally:
        sdk.close()


@pytest.mark.parametrize('backend,max_tokens', [('rewrite', 301), ('langchain', 601)])
def test_output_caps_and_input_budget_block_before_fake_transport(backend, max_tokens):
    calls = []
    guard = HttpBudget(SimpleNamespace(handle_request=lambda request: calls.append(request)), max_requests=25)
    with guard.scope('CR02', backend), pytest.raises(RequestBlocked):
        guard.handle_request(httpx.Request('POST', 'https://fixture.invalid', json={
            'model': 'fixture', 'max_tokens': max_tokens, 'messages': [],
        }))
    assert calls == [] and guard.physical_requests == 0


def test_online_assembly_uses_real_agent_and_langchain_with_fake_sdk_only():
    from eval.run_core_rag_comparison import run_online_comparison

    requests = []
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        user = body['messages'][0]['content']
        missing = 'Python 的 yield' in user
        if body.get('tools') and isinstance(body['messages'][-1]['content'], str):
            content = [{'type': 'tool_use', 'id': 'fixture-search', 'name': 'search_knowledge_base',
                        'input': {'query': user, 'top_k': 2}}]
            stop = 'tool_use'
        else:
            if body.get('tools'):
                evidence = json.loads(body['messages'][-1]['content'][0]['content'])
            else:
                evidence = json.loads(user.split('EVIDENCE_JSON', 1)[1].split('\n', 1)[1])
            node_id = evidence[0]['node_id'] if evidence else None
            reply = {'status': 'not_found', 'answer': '', 'source_ids': []} if missing or node_id is None else {
                'status': 'supported', 'answer': f'fixture evidence [doc:{node_id}]', 'source_ids': [node_id],
            }
            content, stop = [{'type': 'text', 'text': json.dumps(reply)}], 'end_turn'
        return httpx.Response(200, json={
            'id': 'fixture-message', 'type': 'message', 'role': 'assistant', 'model': 'fixture-model',
            'content': content, 'stop_reason': stop, 'stop_sequence': None,
            'usage': {'input_tokens': 5, 'output_tokens': 2,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0},
        })
    sdk = anthropic.Anthropic(api_key='PRIVATE_FIXTURE_CREDENTIAL', max_retries=2,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    try:
        report = run_online_comparison(build_dry_plan(), allow_network=True, new_request_budget=25,
            selected_client=SimpleNamespace(client=sdk, model='fixture-model'))
        assert report['physical_requests'] == len(requests) == 15, [
            (row['case_id'], row['backend'], row['result'].get('answer_status'),
             row['result'].get('answer_error')) for row in report['results']]
        assert len(report['results']) == 10
        for backend in ['strict_agent', 'langchain']:
            rows = [row for row in report['results'] if row['backend'] == backend]
            assert any(row['result']['answer_status'] == 'supported' for row in rows)
            assert any(row['result']['answer_status'] == 'not_found' for row in rows)
        assert report['human_fact_review'] == 'pending'
        assert all(row['input_chars'] <= 16000 for row in report['requests'])
        assert 'PRIVATE_FIXTURE_CREDENTIAL' not in json.dumps(report)
        assert sdk.max_retries == 2
    finally:
        sdk.close()


def test_online_gate_requires_new_budget_before_any_client_access():
    from eval.run_core_rag_comparison import run_online_comparison
    for arguments in [{}, {'allow_network': True}, {'new_request_budget': 25}]:
        with pytest.raises(PermissionError):
            run_online_comparison(build_dry_plan(), **arguments)
    calls = []
    guard = HttpBudget(SimpleNamespace(handle_request=lambda request: calls.append(request)), max_requests=25)
    with guard.scope('CR02', 'langchain'), pytest.raises(RequestBlocked):
        guard.handle_request(httpx.Request('POST', 'https://fixture.invalid', json={
            'model': 'fixture', 'max_tokens': 600,
            'messages': [{'role': 'user', 'content': 'x' * 16001}],
        }))
    assert calls == [] and guard.physical_requests == 0


def test_explicit_deepseek_file_selects_flash_without_cc_switch(tmp_path, monkeypatch):
    from eval.run_core_rag_comparison import load_deepseek_client
    path = tmp_path / '.env.deepseek-smoke'
    path.write_text('DEEPSEEK_API_KEY=PRIVATE_DEEPSEEK_FIXTURE\n', encoding='utf-8')
    seen = []
    monkeypatch.setattr(anthropic, 'Anthropic', lambda **kwargs: seen.append(kwargs) or SimpleNamespace())
    selected = load_deepseek_client(path)
    assert selected.model == 'deepseek-flash'
    assert seen[0]['base_url'] == 'https://api.deepseek.com/anthropic'
    assert seen[0]['max_retries'] == 0
    assert 'PRIVATE_DEEPSEEK_FIXTURE' not in repr(selected)


def test_deepseek_messages_path_and_non_thinking_options_survive_sdk_clone(tmp_path):
    from eval.run_core_rag_comparison import load_deepseek_client
    path = tmp_path / '.env.deepseek-smoke'
    path.write_text('DEEPSEEK_API_KEY=PRIVATE_DEEPSEEK_FIXTURE\n', encoding='utf-8')
    requests = []
    def respond(request):
        requests.append(request)
        return httpx.Response(200, json={
            'id': 'fixture', 'type': 'message', 'role': 'assistant', 'model': 'deepseek-flash',
            'content': [{'type': 'text', 'text': 'fixture'}], 'stop_reason': 'end_turn',
            'usage': {'input_tokens': 2, 'output_tokens': 1},
        })
    selected = load_deepseek_client(path, http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    try:
        selected.client.with_options(max_retries=0).messages.create(model=selected.model, max_tokens=600,
            messages=[{'role': 'user', 'content': 'fixture'}])
        assert len(requests) == 1
        assert str(requests[0].url) == 'https://api.deepseek.com/anthropic/v1/messages'
        assert json.loads(requests[0].content)['thinking'] == {'type': 'disabled'}
    finally:
        selected.client.close()


def test_agent_detail_step_keeps_frozen_fragments_within_physical_input_budget():
    from eval.run_core_rag_comparison import run_online_comparison
    requests, selected_id = [], [None]
    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        user = body['messages'][0]['content']
        if body.get('tools') and len(body['messages']) == 1:
            content = [{'type': 'tool_use', 'id': 'search', 'name': 'search_knowledge_base',
                        'input': {'query': user, 'top_k': 2}}]
            stop = 'tool_use'
        elif body.get('tools') and len(body['messages']) == 3:
            selected_id[0] = json.loads(body['messages'][-1]['content'][0]['content'])[0]['node_id']
            content = [{'type': 'tool_use', 'id': 'detail', 'name': 'get_node_details',
                        'input': {'node_id': selected_id[0]}}]
            stop = 'tool_use'
        else:
            identity = json.loads(user.split('EVIDENCE_JSON', 1)[1].split('\n', 1)[1])[0]['node_id'] if 'EVIDENCE_JSON' in user else selected_id[0]
            content = [{'type': 'text', 'text': json.dumps({'status': 'supported',
                'answer': f'fixture [doc:{identity}]', 'source_ids': [identity]})}]
            stop = 'end_turn'
        return httpx.Response(200, json={'id': 'fixture', 'type': 'message', 'role': 'assistant',
            'model': 'fixture', 'content': content, 'stop_reason': stop,
            'usage': {'input_tokens': 1, 'output_tokens': 1,
                      'cache_read_input_tokens': 0, 'cache_creation_input_tokens': 0}})
    sdk = anthropic.Anthropic(api_key='fixture', max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(respond)))
    try:
        report = run_online_comparison(build_dry_plan(), allow_network=True, new_request_budget=20,
                                      selected_client=SimpleNamespace(client=sdk, model='fixture'))
        assert not report['halted']
        assert len(report['results']) == 10 and report['physical_requests'] == 20
        assert all(row['input_chars'] <= 16000 for row in report['requests'])
        assert all([step['tool'] for step in row['observed']] == ['search_knowledge_base', 'get_node_details']
                   for row in report['results'] if row['backend'] == 'strict_agent')
    finally:
        sdk.close()
