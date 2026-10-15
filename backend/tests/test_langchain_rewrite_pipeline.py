"""真正 LangChain 生命周期中的单次改写、双检索分支与原问生成。"""

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.models.node import KnowledgeNode
from app.services.langchain_rag import run_langchain_rag


class PipelineModel(BaseChatModel):
    reply: str
    calls: int = 0
    seen: list = Field(default_factory=list)
    usage: dict | None = None

    @property
    def _llm_type(self):
        return 'offline-rewrite-pipeline'

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        self.seen.append(messages)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(
            content=self.reply, usage_metadata=self.usage,
        ))])


@pytest.fixture
def notes(db):
    db.add_all([
        KnowledgeNode(id=7, user_id=3, title='原问证据', content='原始证据'),
        KnowledgeNode(id=8, user_id=4, title='FOREIGN_SECRET', content='FOREIGN_SECRET'),
        KnowledgeNode(id=10, user_id=3, title='空正文', content=''),
        KnowledgeNode(id=11, user_id=3, title='改写证据', content='扩展证据'),
    ])
    db.commit()
    return db


def generation():
    return PipelineModel(reply='{"status":"supported","answer":"原始证据 [doc:7]",'
        '"source_ids":[7]}', usage={'input_tokens': 10, 'output_tokens': 4, 'total_tokens': 14})


def rewriting(reply='向量检索是什么？'):
    return PipelineModel(reply=json.dumps({'rewrite': reply}, ensure_ascii=False),
        usage={'input_tokens': 3, 'output_tokens': 2, 'total_tokens': 5})


def test_default_off_keeps_one_retrieval_and_one_generation(notes):
    calls = []
    answer, rewrite = generation(), rewriting()
    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3, model=answer,
        rewrite_model=rewrite, retrieval=lambda query, **kw: calls.append((query, kw)) or [
            {'node_id': 7, 'content': '原始证据'},
        ])
    assert result['answer_status'] == 'supported'
    assert result['model_calls'] == answer.calls == 1 and rewrite.calls == 0
    assert calls == [('向量俭索是什么？', {'user_id': 3, 'top_k': 3})]
    assert result['rewrite_model_calls'] == 0


def test_accepted_rewrite_runs_original_branch_and_filters_both_before_observation(notes):
    calls, observed = [], []
    answer, rewrite = generation(), rewriting()

    def retrieve(query, **kwargs):
        calls.append((query, kwargs))
        protected = [{'node_id': 8, 'content': 'FOREIGN_SECRET'},
                     {'node_id': 9, 'content': 'DELETED_SECRET'},
                     {'node_id': 10, 'content': 'EMPTY_SECRET'}]
        return protected + [{'node_id': 7, 'content': '原始证据', 'score': -999}] + ([
            {'node_id': 7, 'content': '原始证据', 'score': 999999},
            {'node_id': 11, 'content': '扩展证据', 'score': 999999},
        ] if query == '向量检索是什么？' else [])

    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3, model=answer,
        rewrite_enabled=True, rewrite_model=rewrite, retrieval=retrieve, top_k=2,
        observe_tool_result=lambda *args: observed.append(args))
    assert result['answer_status'] == 'supported'
    assert [row[0] for row in calls] == ['向量俭索是什么？', '向量检索是什么？']
    assert all(row[1] == {'user_id': 3, 'top_k': 2} for row in calls)
    assert len(observed) == 2
    assert all('SECRET' not in row[2] for row in observed)
    visible = answer.seen[0][1].content
    assert 'CURRENT_QUESTION:\n向量俭索是什么？' in visible
    assert 'CURRENT_QUESTION:\n向量检索是什么？' not in visible
    assert visible.count('原始证据') == 1
    assert '扩展证据' in visible and 'SECRET' not in visible
    assert result['model_calls'] == rewrite.calls + answer.calls == 2
    assert result['rewrite_usage']['total_input_tokens'] == 3
    assert result['generation_usage']['total_input_tokens'] == 10
    assert result['usage'] == result['generation_usage']
    selected = [step for step in result['steps'] if step['type'] == 'evidence_selection'][-1]
    assert selected['branch_count'] == 2 and selected['chunk_count'] == 2
    assert {item['node_id'] for item in selected['selected']} == {7, 11}


def test_rewrite_failure_returns_to_original_retriever_without_extra_retrieval(notes):
    calls = []
    answer = generation()
    rewrite = PipelineModel(reply='bad JSON')
    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3, model=answer,
        rewrite_enabled=True, rewrite_model=rewrite,
        retrieval=lambda query, **kw: calls.append(query) or [{'node_id': 7, 'content': '原始证据'}])
    assert result['answer_status'] == 'supported'
    assert calls == ['向量俭索是什么？']
    assert result['model_calls'] == 2
    assert result['rewrite_trace'][-1]['failure_reason'] == 'invalid_rewrite_contract'


def test_large_merged_evidence_fails_before_generation_and_keeps_rewrite_count(notes):
    notes.get(KnowledgeNode, 7).content = '大证据' * 2000
    notes.commit()
    answer, rewrite = generation(), rewriting()
    calls = []
    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3, model=answer,
        rewrite_enabled=True, rewrite_model=rewrite, max_input_chars=2000,
        retrieval=lambda query, **kw: calls.append(query) or [{'node_id': 7, 'content': '大证据' * 2000}])
    assert result['answer_error'] == 'input_budget_exceeded'
    assert rewrite.calls == result['model_calls'] == 1 and answer.calls == 0
    assert calls == ['向量俭索是什么？', '向量检索是什么？']
    assert result['generation_model_calls'] == 0
    assert result['input_budget']['input_chars'] > 2000
    assert any(step['type'] == 'input_budget_rejected' for step in result['steps'])


def test_rrf_selection_caps_parents_and_two_complete_chunks_per_parent(notes):
    answer, rewrite = generation(), rewriting()
    rows = [{'node_id': 7, 'content': f'整块-{index}'} for index in range(4)] + [
        {'node_id': 11, 'content': '第二父文档整块'},
    ]
    notes.get(KnowledgeNode, 7).content = '\n'.join(row['content'] for row in rows if row['node_id'] == 7)
    notes.get(KnowledgeNode, 11).content = '第二父文档整块'
    notes.commit()
    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3, model=answer,
        rewrite_enabled=True, rewrite_model=rewrite, top_k=1,
        retrieval=lambda *args, **kwargs: rows)
    selected = [step for step in result['steps'] if step['type'] == 'evidence_selection'][-1]
    assert selected['chunk_count'] == 2
    assert [item['node_id'] for item in selected['selected']] == [7, 7]
    content = answer.seen[0][1].content
    assert '整块-0' in content and '整块-1' in content
    assert '整块-2' not in content and '第二父文档整块' not in content


def test_authenticated_ai_client_is_reused_for_once_rewrite_and_generation(notes):
    clone = MagicMock()
    clone.messages.create.side_effect = [
        SimpleNamespace(content=[SimpleNamespace(type='text', text='{"rewrite":"向量检索是什么？"}')],
            stop_reason='end_turn', usage=SimpleNamespace(input_tokens=3, output_tokens=2,
                cache_read_input_tokens=0, cache_creation_input_tokens=0)),
        SimpleNamespace(content=[SimpleNamespace(type='text', text=generation().reply)],
            stop_reason='end_turn', usage=SimpleNamespace(input_tokens=10, output_tokens=4,
                cache_read_input_tokens=0, cache_creation_input_tokens=0)),
    ]
    sdk = MagicMock()
    sdk.with_options.return_value = clone
    calls = []
    result = run_langchain_rag(notes, '向量俭索是什么？', user_id=3,
        ai_client=SimpleNamespace(client=sdk, model='authenticated-fixture'), rewrite_enabled=True,
        retrieval=lambda query, **kw: calls.append(query) or [{'node_id': 7, 'content': '原始证据'}])
    assert result['answer_status'] == 'supported'
    assert result['model_calls'] == clone.messages.create.call_count == 2
    assert calls == ['向量俭索是什么？', '向量检索是什么？']
    requests = [call.kwargs for call in clone.messages.create.call_args_list]
    assert all(request['model'] == 'authenticated-fixture' for request in requests)
    assert requests[0]['max_tokens'] == 300 and requests[1]['max_tokens'] == 1200
    assert all(call.kwargs['max_retries'] == 0 for call in sdk.with_options.call_args_list)
    assert result['rewrite_usage']['total_input_tokens'] == 3
    assert result['usage']['total_input_tokens'] == result['generation_usage']['total_input_tokens'] == 10
