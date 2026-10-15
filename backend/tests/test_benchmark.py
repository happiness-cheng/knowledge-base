"""统一评测通过公开接口区分命中文档、证据覆盖、失败与无效用例。"""

import json

import pytest

from eval.benchmark import BenchmarkCase, BenchmarkObservation, evaluate, load_cases


def test_node_hit_does_not_imply_answer_evidence_is_in_context():
    case = BenchmarkCase('tail', '问题', 7, '答案在尾部', '', 'B', 'authored')
    report = evaluate([case], {7: '开头内容。答案在尾部'}, lambda _: BenchmarkObservation(
        retrieved=[{'node_id': 7, 'content': '开头内容'}],
        answer='回答 [doc:7]', citations=[7],
    ), {'mode': 'offline_fixture'})
    row = report['cases'][0]
    assert row['hit_at_3'] == 1
    assert row['evidence_in_context'] == 0
    assert report['summary']['evidence_in_context'] == 0


def test_missing_gold_is_reported_separately_and_never_executed():
    cases = [BenchmarkCase('missing', '问题', 9, '证据', '', 'A', 'authored')]
    def forbidden(_):
        raise AssertionError('无效 gold 不应进入执行器')
    report = evaluate(cases, {7: '证据'}, forbidden, {})
    assert report['summary']['invalid_cases'] == 1
    assert report['summary']['valid_cases'] == 0
    assert report['cases'][0]['status'] == 'invalid_gold'


def test_error_is_in_denominator_and_non_answer_is_not_refusal_success():
    cases = [BenchmarkCase('negative', '今天收盘多少', None, None, None, 'N', 'authored')]
    def failure(_):
        raise RuntimeError('provider unavailable')
    report = evaluate(cases, {}, failure, {})
    assert report['summary']['execution_errors'] == 1
    assert report['summary']['refusal_rate'] == 0
    assert report['cases'][0]['status'] == 'execution_error'


def test_refusal_and_citations_have_independent_checks():
    cases = [BenchmarkCase('negative', '未知问题', None, None, None, 'N', 'authored')]
    report = evaluate(cases, {}, lambda _: BenchmarkObservation(
        answer='无法确认', refused=True, citations=[999], retrieved=[]
    ), {})
    assert report['summary']['refusal_rate'] == 0
    assert report['cases'][0]['citation_valid'] is False


def test_refusal_with_valid_background_citations_is_not_hidden_or_scored_as_hallucination():
    case = BenchmarkCase('negative', '未知工资', None, None, None)
    report = evaluate([case], {7: '重试次数是 2'}, lambda _: BenchmarkObservation(
        answer='NOT_FOUND_IN_KB，只有重试背景 [doc:7]', refused=True, citations=[7],
        retrieved=[{'node_id': 7, 'content': '重试次数是 2'}],
    ), {})
    assert report['summary']['refusal_detected_rate'] == 1
    assert report['summary']['refusal_with_citations_rate'] == 1
    assert report['summary']['refusal_rate'] == 0  # 保留旧严格指标，不能改口径刷分。
    assert report['summary']['citation_valid_rate'] == 1
    assert report['cases'][0]['review_required']


def test_refusal_detection_does_not_exclude_execution_failures_from_denominator():
    cases = [BenchmarkCase('one', '问题', None, None, None),
             BenchmarkCase('two', '问题', None, None, None)]
    def execute(case):
        if case.case_id == 'two':
            raise RuntimeError('provider failed')
        return BenchmarkObservation(answer='NOT_FOUND_IN_KB', refused=True)
    report = evaluate(cases, {}, execute, {})
    assert report['summary']['refusal_detected_rate'] == .5
    assert report['summary']['refusal_with_citations_rate'] == 0


def test_retrieval_only_does_not_claim_answer_metrics():
    cases = [BenchmarkCase('negative', '未知问题', None, None, None)]
    report = evaluate(cases, {}, lambda _: BenchmarkObservation(), {'mode': 'retrieval'})
    assert report['summary']['refusal_rate'] is None
    assert report['summary']['citation_valid_rate'] is None
    assert report['layers']['note_type:unknown']['refusal_rate'] is None


def test_layers_and_percentiles_keep_explicit_denominators():
    cases = [BenchmarkCase('one', '问题', 1, '证据', '', 'A', 'chatlog'),
             BenchmarkCase('two', '问题', 2, '证据', '', 'B', 'authored')]
    report = evaluate(cases, {1: '证据', 2: '证据'}, lambda case: BenchmarkObservation(
        retrieved=[{'node_id': 1, 'content': '证据'}], latency_ms=10 if case.case_id == 'one' else 50,
    ), {'mode': 'offline_fixture'})
    assert report['summary']['hit_at_3'] == 0.5
    assert report['layers']['note_type:A']['positive_cases'] == 1
    assert report['layers']['query_source:authored']['hit_at_3'] == 0
    assert report['summary']['latency_p95_ms'] == 48
    assert report['summary']['total_input_tokens'] is None


def test_existing_v3_case_format_loads_and_duplicate_ids_fail(tmp_path):
    path = tmp_path / 'cases.json'
    row = ['Q1', 7, 'A', 'authored', '问题', '证据', '']
    path.write_text(json.dumps({'cases': [row]}, ensure_ascii=False), encoding='utf-8')
    assert load_cases(path)[0].gold_node_id == 7
    path.write_text(json.dumps({'cases': [row, row]}), encoding='utf-8')
    with pytest.raises(ValueError, match='duplicate'):
        load_cases(path)


def test_application_adapter_observes_the_context_seen_by_real_agent(monkeypatch):
    from types import SimpleNamespace
    from eval.run_benchmark import ApplicationExecutor
    from app.services import agent_service
    replies = iter([
        SimpleNamespace(content=[SimpleNamespace(type='tool_use', name='search_knowledge_base',
            input={'query': '证据'}, id='call-1')], usage=SimpleNamespace(input_tokens=5, output_tokens=3)),
        SimpleNamespace(content=[SimpleNamespace(type='text', text='答案 [doc:7]')],
            usage=SimpleNamespace(input_tokens=8, output_tokens=4)),
    ])
    class Client:
        def chat_with_tools(self, **kwargs):
            return next(replies)
    monkeypatch.setattr(agent_service, 'execute_tool', lambda *a, **kw: json.dumps([
        {'node_id': 7, 'content': '答案证据', 'title': '来源'}
    ]))
    case = BenchmarkCase('one', '问题', 7, '答案证据', '', 'A', 'authored')
    result = ApplicationExecutor(None, 12, Client())(case)
    assert result.retrieved[0]['content'] == '答案证据'
    assert result.citations == [7]
    assert result.input_tokens == 13
    assert result.output_tokens == 7
    assert any(step.get('tool_name') == 'search_knowledge_base' for step in result.steps)


def test_adapter_reports_budget_failure_instead_of_treating_error_as_answer(monkeypatch):
    from eval.run_benchmark import ApplicationExecutor
    from app.services import agent_service
    class Client:
        budget_exceeded = True
    monkeypatch.setattr(agent_service, 'run_agent', lambda *a, **kw: {
        'content': 'Agent encountered an error: budget exceeded', 'source_ids': [],
        'found_in_kb': False, 'steps': []})
    with pytest.raises(RuntimeError, match='budget'):
        ApplicationExecutor(None, 1, Client())(BenchmarkCase('one', '问题', None, None, None))


def test_multi_evidence_input_is_immutable_and_legacy_formats_still_load(tmp_path):
    from dataclasses import FrozenInstanceError
    from eval.benchmark import EvidenceTarget

    path = tmp_path / 'cases.json'
    path.write_text(json.dumps({'cases': [
        ['legacy', 7, 'A', 'authored', '旧格式问题', '证据一', ''],
        {'case_id': 'v2', 'question': '旧字典问题', 'gold_node_id': 8,
         'evidence_head': '证据二', 'evidence_tail': None},
        {'case_id': 'multi', 'question': '组合问题', 'gold_evidence': [
            {'node_id': 7, 'head': '证据一'},
            {'node_id': 8, 'head': '证据二', 'tail': '结尾'},
        ]},
        {'case_id': 'negative', 'question': '未知问题'},
    ]}, ensure_ascii=False), encoding='utf-8')
    cases = load_cases(path)
    assert cases[0].gold_node_id == 7
    assert cases[1].gold_node_id == 8
    assert cases[2].gold_node_id is None
    assert cases[2].gold_evidence == (
        EvidenceTarget(7, '证据一'), EvidenceTarget(8, '证据二', '结尾'),
    )
    with pytest.raises(FrozenInstanceError):
        cases[2].gold_evidence[0].head = '篡改'
    assert cases[3].gold_evidence == ()


def test_multi_evidence_rejects_conflicting_legacy_fields_and_invalid_targets():
    from eval.benchmark import EvidenceTarget

    with pytest.raises(ValueError, match='mix'):
        BenchmarkCase('mixed', '问题', 7, '证据', '',
                      gold_evidence=[EvidenceTarget(8, '另一证据')])
    with pytest.raises(ValueError, match='mix'):
        BenchmarkCase('mixed', '问题', evidence_head='旧锚点',
                      gold_evidence=[EvidenceTarget(8, '另一证据')])
    for node_id in (0, -1, True, '7'):
        with pytest.raises(ValueError, match='node id'):
            EvidenceTarget(node_id, '证据')
    with pytest.raises(ValueError, match='head'):
        EvidenceTarget(7, '  ')


def test_multi_evidence_deduplicates_identical_intervals_but_keeps_same_document_spans():
    from eval.benchmark import EvidenceTarget

    mutable_targets = [EvidenceTarget(7, '证据 一', '结尾'),
                       EvidenceTarget(7, '证据一', '结尾'),
                       EvidenceTarget(7, '另一个区间')]
    case = BenchmarkCase('multi', '问题', gold_evidence=mutable_targets)
    mutable_targets.clear()
    assert case.gold_evidence == (
        EvidenceTarget(7, '证据 一', '结尾'), EvidenceTarget(7, '另一个区间'),
    )


def test_multi_document_recall_and_evidence_coverage_are_distinct_and_all_required():
    from eval.benchmark import EvidenceTarget

    case = BenchmarkCase('multi', '组合问题', gold_evidence=[
        EvidenceTarget(7, '证据甲'), EvidenceTarget(7, '证据乙'),
        EvidenceTarget(8, '证据丙', '结束'),
    ])
    report = evaluate([case], {7: '证据甲 证据乙', 8: '证据丙 结束', 99: '背景'},
                      lambda _: BenchmarkObservation(retrieved=[
                          {'node_id': 7, 'content': '证据甲'},
                          {'node_id': 7, 'content': '证据甲'},
                          {'node_id': 99, 'content': '背景'},
                          {'node_id': 8, 'content': '证据丙'},
                      ]), {'mode': 'retrieval'})
    row = report['cases'][0]
    assert row['answerable'] is True
    assert row['gold_document_ids'] == [7, 8]
    assert row['document_recall_at_1'] == .5
    assert row['document_recall_at_3'] == 1
    assert row['document_recalled_at_1'] == 1
    assert row['document_recalled_at_3'] == 2
    assert row['document_targets'] == 2
    assert row['evidence_covered'] == 1
    assert row['evidence_targets'] == 3
    assert row['evidence_coverage'] == pytest.approx(1 / 3)
    assert row['evidence_all_covered'] == 0
    assert row['evidence_in_context'] == 0
    assert row['hit_at_1'] == 1  # 多文档 Hit 仅表示任一必需文档命中。
    assert row['reciprocal_rank'] == 1
    assert report['summary']['evidence_covered'] == 1
    assert report['summary']['evidence_targets'] == 3
    assert report['summary']['document_recall_at_1'] == .5
    assert report['schema_version'] == 2
    assert 'document_recall_at_1' in report['metric_definitions']


def test_context_coverage_requires_each_interval_in_one_retrieved_block():
    from eval.benchmark import EvidenceTarget

    case = BenchmarkCase('multi', '问题', gold_evidence=[
        EvidenceTarget(7, '开始', '结束'), EvidenceTarget(8, '必要证据'),
    ])
    report = evaluate([case], {7: '开始 中间 结束', 8: '必要证据'},
                      lambda _: BenchmarkObservation(retrieved=[
                          {'node_id': 7, 'content': '开始 中间'},
                          {'node_id': 7, 'content': '中间 结束'},
                          {'node_id': 999, 'content': '必要证据'},
                      ]), {})
    row = report['cases'][0]
    assert row['evidence_covered'] == 0
    assert row['evidence_targets'] == 2
    assert row['document_recall_at_3'] == .5
    assert row['evidence_all_covered'] == 0


@pytest.mark.parametrize('corpus', [
    {7: '证据甲'}, {7: '证据甲', 8: '错误内容'},
    {7: '证据甲', 8: '结束 证据乙'},
])
def test_any_invalid_gold_makes_whole_multi_case_invalid_without_executing(corpus):
    from eval.benchmark import EvidenceTarget

    case = BenchmarkCase('multi', '问题', gold_evidence=[
        EvidenceTarget(7, '证据甲'), EvidenceTarget(8, '证据乙', '结束'),
    ])
    calls = []
    report = evaluate([case], corpus, lambda value: calls.append(value), {})
    assert calls == []
    assert report['cases'][0]['status'] == 'invalid_gold'
    assert report['summary']['positive_cases'] == 0
    assert report['summary']['invalid_cases'] == 1
    assert report['summary']['document_targets'] == 0
    assert report['summary']['evidence_targets'] == 0


def test_multi_error_keeps_document_and_evidence_denominators_and_usage_unknown():
    from eval.benchmark import EvidenceTarget

    cases = [BenchmarkCase('ok', '问题', 7, '证据甲', ''),
             BenchmarkCase('error', '问题', gold_evidence=[
                 EvidenceTarget(7, '证据甲'), EvidenceTarget(8, '证据乙'),
             ]), BenchmarkCase('negative', '未知问题')]
    def execute(case):
        if case.case_id == 'error':
            raise RuntimeError('provider unavailable')
        return BenchmarkObservation(retrieved=[{'node_id': 7, 'content': '证据甲'}],
                                    refused=case.case_id == 'negative',
                                    input_tokens=10, output_tokens=3)
    report = evaluate(cases, {7: '证据甲', 8: '证据乙'}, execute, {})
    summary = report['summary']
    assert summary['positive_cases'] == 2
    assert summary['negative_cases'] == 1
    assert summary['execution_errors'] == 1
    assert summary['document_recall_at_3'] == .5
    assert summary['document_recalled_at_3'] == 1
    assert summary['document_targets'] == 3
    assert summary['evidence_covered'] == 1
    assert summary['evidence_targets'] == 3
    assert summary['evidence_coverage'] == pytest.approx(1 / 3)
    assert summary['evidence_all_covered'] == .5
    assert summary['total_input_tokens'] is None
    assert summary['usage_status'] == 'unknown'
    assert report['cases'][0]['usage_status'] == 'complete'
    assert report['cases'][1]['usage_status'] == 'unknown'
    assert report['cases'][2]['evidence_coverage'] is None
    assert summary['refusal_rate'] == 1


def test_summary_distinguishes_macro_document_recall_from_evidence_micro_coverage():
    from eval.benchmark import EvidenceTarget

    cases = [BenchmarkCase('single', '问题', 7, '证据甲', ''),
             BenchmarkCase('multi', '问题', gold_evidence=[
                 EvidenceTarget(7, '证据甲'), EvidenceTarget(8, '证据乙'),
                 EvidenceTarget(8, '证据丙'),
             ])]
    report = evaluate(cases, {7: '证据甲', 8: '证据乙 证据丙'},
                      lambda _: BenchmarkObservation(
                          retrieved=[{'node_id': 7, 'content': '证据甲'}]), {})
    summary = report['summary']
    assert summary['document_recall_at_3'] == .75
    assert summary['document_recalled_at_3'] == 2
    assert summary['document_targets'] == 3
    assert summary['evidence_covered'] == 2
    assert summary['evidence_targets'] == 4
    assert summary['evidence_coverage'] == .5
    assert summary['evidence_all_covered'] == .5


def test_all_evidence_coverage_can_be_spread_across_blocks_of_same_document():
    from eval.benchmark import EvidenceTarget

    case = BenchmarkCase('multi', '问题', gold_evidence=[
        EvidenceTarget(7, '证据甲'), EvidenceTarget(7, '证据乙'), EvidenceTarget(8, '证据丙'),
    ])
    report = evaluate([case], {7: '证据甲 证据乙', 8: '证据丙'},
                      lambda _: BenchmarkObservation(retrieved=[
                          {'node_id': 7, 'content': '证据甲'},
                          {'node_id': 7, 'content': '证据乙'},
                          {'node_id': 8, 'content': '证据丙'},
                      ]), {})
    row = report['cases'][0]
    assert row['evidence_covered'] == 3
    assert row['evidence_all_covered'] == 1
    assert row['evidence_in_context'] == 1
    assert row['document_recall_at_3'] == 1
    assert row['document_targets'] == 2


def test_multi_evidence_report_renders_denominators_and_metric_definitions():
    from eval.benchmark import EvidenceTarget, render_markdown

    case = BenchmarkCase('multi', '问题', gold_evidence=[
        EvidenceTarget(7, '证据甲'), EvidenceTarget(8, '证据乙'),
    ])
    report = evaluate([case], {7: '证据甲', 8: '证据乙'},
                      lambda _: BenchmarkObservation(
                          retrieved=[{'node_id': 7, 'content': '证据甲'}]), {})
    encoded = json.loads(json.dumps(report, ensure_ascii=False))
    text = render_markdown(encoded)
    assert '| evidence spans |' in text
    assert '| 1/2 | 0 |' in text
    assert 'macro' in text
    assert 'micro' in text


def test_markdown_renderer_still_accepts_existing_schema_two_report():
    from eval.benchmark import render_markdown

    text = render_markdown({
        'schema_version': 2, 'metadata': {}, 'summary': {'hit_at_3': 1},
        'cases': [{'case_id': 'old', 'status': 'ok', 'rank': 1,
                   'evidence_in_context': 1, 'citation_valid': True}],
        'limitations': ['旧报告'],
    })
    assert '| old | ok | 1 | 1 | True |' in text
    assert '旧报告' in text


def test_multi_gold_does_not_enter_actual_agent_prompt_or_inflate_observed_context(monkeypatch):
    from types import SimpleNamespace
    from eval.benchmark import EvidenceTarget
    from eval.run_benchmark import ApplicationExecutor
    from app.services import agent_service

    requests = []
    replies = iter([
        SimpleNamespace(content=[SimpleNamespace(type='tool_use', name='search_knowledge_base',
            input={'query': '证据甲'}, id='call-multi')],
            usage=SimpleNamespace(input_tokens=5, output_tokens=3)),
        SimpleNamespace(content=[SimpleNamespace(type='text', text='证据甲 [doc:7]')],
            usage=SimpleNamespace(input_tokens=8, output_tokens=4)),
    ])
    class Client:
        def chat_with_tools(self, **kwargs):
            requests.append(json.dumps(kwargs, ensure_ascii=False, default=str))
            return next(replies)
    monkeypatch.setattr(agent_service, 'execute_tool', lambda *a, **kw: json.dumps([
        {'node_id': 7, 'content': '证据甲', 'title': '真实工具结果'},
    ]))
    hidden = 'never_retrieved_secret_evidence'
    case = BenchmarkCase('multi', '组合问题', gold_evidence=[
        EvidenceTarget(7, '证据甲'), EvidenceTarget(8, hidden),
    ])
    report = evaluate([case], {7: '证据甲', 8: hidden}, ApplicationExecutor(None, 12, Client()), {})
    row = report['cases'][0]
    assert row['status'] == 'ok'
    assert row['retrieved'] == [{'node_id': 7, 'content': '证据甲', 'title': '真实工具结果'}]
    assert row['answer'] == '证据甲 [doc:7]'
    assert row['citations'] == [7]
    assert row['document_recall_at_3'] == .5
    assert row['evidence_covered'] == 1
    assert row['evidence_targets'] == 2
    assert all(hidden not in request for request in requests)


def test_partial_usage_is_unknown_even_when_input_token_total_is_available():
    report = evaluate([BenchmarkCase('negative', '未知问题')], {},
                      lambda _: BenchmarkObservation(refused=True, input_tokens=7), {})
    assert report['cases'][0]['usage_status'] == 'unknown'
    assert report['summary']['usage_status'] == 'unknown'
    assert report['summary']['total_input_tokens'] == 7
    assert report['summary']['total_output_tokens'] is None
    assert report['summary']['document_recall_at_3'] is None
    assert report['summary']['evidence_coverage'] is None
