"""严格 LangChain 候选必须经过真实鉴权路由，默认 Agent 行为保持兼容。"""

from unittest.mock import Mock, patch

import pytest

from app.models.chat import Message


def test_langchain_route_uses_authenticated_user_and_selected_client(client, db):
    conversation = client.post('/api/chat/conversations', json={}).json()
    selected_client = Mock()
    result = {
        'content': '知识库未找到证据。', 'source_ids': [],
        'is_from_kb': True, 'found_in_kb': False,
        'answer_status': 'not_found', 'steps': [], 'web_sources': [],
    }
    with patch('app.routers.chat.get_client_for_user', return_value=selected_client), patch(
        'app.routers.chat.run_langchain_candidate', return_value=result, create=True,
    ) as candidate, patch('app.routers.chat.run_agent', return_value=result) as agent:
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={'content': '我的问题', 'kb_only': True, 'backend': 'langchain'},
        )

    assert response.status_code == 200, response.text
    assert response.json()['answer_status'] == 'not_found'
    candidate.assert_called_once()
    assert candidate.call_args.args[1] == '我的问题'
    assert candidate.call_args.kwargs['ai_client'] is selected_client
    assert candidate.call_args.kwargs['user_id'] > 0
    agent.assert_not_called()
    assert db.query(Message).count() == 2


@pytest.mark.parametrize('body', [
    {'content': 'x', 'backend': 'langchain'},
    {'content': 'x', 'backend': 'langchain', 'kb_only': True, 'ai_search': True},
    {'content': 'x', 'backend': 'invalid', 'kb_only': True},
    {'content': 'x', 'kb_only': True, 'retrieval_mode': 'hybrid'},
    {'content': 'x', 'kb_only': True, 'backend': 'langchain', 'rerank': True},
    {'content': 'x', 'kb_only': True, 'rewrite': True},
    {'content': 'x', 'kb_only': True, 'backend': 'langchain', 'rewrite_bindings': {'它': 'HTTP2'}},
])
def test_invalid_backend_combination_is_rejected_before_persistence(client, db, body):
    conversation = client.post('/api/chat/conversations', json={}).json()
    response = client.post(
        f"/api/chat/conversations/{conversation['id']}/messages", json=body,
    )
    assert response.status_code == 422
    assert db.query(Message).count() == 0


def test_optional_candidates_are_scoped_by_server_and_forwarded_to_real_chain(client):
    conversation = client.post('/api/chat/conversations', json={}).json()
    candidate = Mock()
    candidate.trace = {'mode': 'hybrid'}
    candidate.history = []
    with patch('app.routers.chat.make_retrieval_candidate', return_value=candidate, create=True) as make, patch(
        'app.routers.chat.run_langchain_candidate', return_value={
            'content': '未找到', 'source_ids': [], 'answer_status': 'not_found',
        }, create=True,
    ) as run:
        response = client.post(f"/api/chat/conversations/{conversation['id']}/messages", json={
            'content': 'HTTP2有什么？', 'kb_only': True, 'backend': 'langchain',
            'retrieval_mode': 'hybrid', 'rerank': True, 'rewrite': True,
        })
    assert response.status_code == 200, response.text
    make.assert_called_once()
    assert make.call_args.kwargs['user_id'] == run.call_args.kwargs['user_id']
    assert make.call_args.kwargs['mode'] == 'hybrid'
    assert make.call_args.kwargs['rerank'] is True
    assert run.call_args.kwargs['retrieval'] is candidate
    assert run.call_args.kwargs['rewrite_enabled'] is True


def test_default_backend_still_calls_custom_agent(client):
    conversation = client.post('/api/chat/conversations', json={}).json()
    with patch('app.routers.chat.run_agent', return_value={
        'content': '默认回答', 'source_ids': [], 'answer_status': 'supported',
    }) as agent, patch('app.routers.chat.run_langchain_candidate', create=True) as candidate:
        response = client.post(
            f"/api/chat/conversations/{conversation['id']}/messages",
            json={'content': 'x', 'kb_only': True},
        )
    assert response.status_code == 200
    agent.assert_called_once()
    candidate.assert_not_called()


def test_authenticated_http_route_runs_real_chain_and_sdk_once(client, db):
    import json
    from types import SimpleNamespace

    import anthropic
    import httpx2

    from app.models.node import KnowledgeNode

    node = client.post('/api/nodes', json={
        'title': 'HTTP2', 'content': 'HTTP2支持多路复用。',
    }).json()
    node_id = node['id']
    owned = db.query(KnowledgeNode).filter_by(id=node_id).one()
    conversation = client.post('/api/chat/conversations', json={}).json()
    bodies = []

    def respond(request):
        bodies.append(json.loads(request.content))
        return httpx2.Response(200, json={
            'id': 'msg-fixture', 'type': 'message', 'role': 'assistant', 'model': 'fixture',
            'content': [{'type': 'text', 'text': json.dumps({
                'status': 'supported', 'answer': f'支持多路复用 [doc:{node_id}]',
                'source_ids': [node_id],
            }, ensure_ascii=False)}], 'stop_reason': 'end_turn', 'stop_sequence': None,
            'usage': {'input_tokens': 10, 'output_tokens': 4},
        })

    with httpx2.Client(transport=httpx2.MockTransport(respond), trust_env=False) as transport:
        sdk = anthropic.Anthropic(api_key='fixture-only', http_client=transport, max_retries=2)
        selected = SimpleNamespace(client=sdk, model='fixture')
        with patch('app.routers.chat.get_client_for_user', return_value=selected), patch(
            'app.services.rag_service.retrieve_relevant_nodes',
            return_value=[{'node_id': node_id, 'content': owned.content}],
        ) as retrieval:
            response = client.post(
                f"/api/chat/conversations/{conversation['id']}/messages",
                json={'content': 'HTTP2有什么特性？', 'kb_only': True, 'backend': 'langchain'},
            )

    assert response.status_code == 200, response.text
    assert response.json()['answer_status'] == 'supported'
    assert response.json()['source_node_ids'] == [node_id]
    assert len(bodies) == 1
    assert retrieval.call_args.kwargs['user_id'] == owned.user_id
    assistant = db.query(Message).filter_by(role='assistant').one()
    assert [source.id for source in assistant.sources] == [node_id]
