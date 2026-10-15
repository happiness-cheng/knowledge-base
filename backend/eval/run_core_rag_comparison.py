"""冻结 5 题的有限框架对照；默认纯 dry-run，不加载应用或个人配置。"""

import argparse
import json
import os
import re
import sys
from collections import Counter
from contextlib import ExitStack, contextmanager
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from eval.core_corpus import load_manifest_corpus, validate_core_dataset

CASE_IDS = ('CR02', 'CR07', 'CR13', 'CR19', 'CR26')


def _hash(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _terms(value):
    ascii_terms = re.findall(r'[A-Za-z_][A-Za-z0-9_]*', value.lower())
    chinese = re.findall(r'[\u4e00-\u9fff]+', value)
    return set(ascii_terms + [part[index:index + 2] for part in chinese for index in range(len(part) - 1)])


def build_dry_plan():
    manifest_path = BACKEND_ROOT / 'eval/fixtures/core-rag-corpus-20261013.json'
    dataset_path = BACKEND_ROOT / 'eval/fixtures/core-rag-20261013.json'
    corpus = load_manifest_corpus(manifest_path, REPOSITORY_ROOT)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
    cases = {case.case_id: case for case in validate_core_dataset(dataset_path, corpus)}
    sources = {source['node_id']: source for source in manifest['documents']}
    chunks = []
    for node_id, content in corpus.items():
        for paragraph in content.replace('\r\n', '\n').split('\n\n'):
            for offset in range(0, len(paragraph), 800):
                piece = paragraph[offset:offset + 800]
                if piece.strip():
                    chunks.append({'node_id': node_id, 'title': sources[node_id]['title'], 'content': piece})
    selected, frozen = [], {}
    for case_id in CASE_IDS:
        case = cases[case_id]
        details = dataset['case_metadata'][case_id]
        if details['split'] != 'development':
            raise ValueError('online subset must remain development-only')
        query_terms = _terms(case.question)
        ranked = sorted(enumerate(chunks), key=lambda pair: (
            -len(query_terms & _terms(pair[1]['content'] + pair[1]['title'])), pair[0],
        ))
        parents, counts, rows = [], Counter(), []
        for _index, row in ranked:
            node_id = row['node_id']
            if node_id not in parents and len(parents) < 2:
                parents.append(node_id)
            if node_id not in parents or counts[node_id] >= 2:
                continue
            rows.append(dict(row))
            counts[node_id] += 1
            if len(rows) == 4:
                break
        frozen[case_id] = rows
        selected.append({'case_id': case_id, 'question': case.question, 'split': details['split'],
                         'query_category': details['query_category'], 'gold_sha256': _hash(asdict(case))})
    return {
        'mode': 'dry_run', 'physical_requests': 0, 'physical_request_limit': 25,
        'input_chars_limit': 16000, 'output_tokens_limit': 600, 'rewrite_output_tokens_limit': 300,
        'cases': selected, 'frozen_retrieval': frozen, 'retrieval_sha256': _hash(frozen),
        'dataset_sha256': sha256(dataset_path.read_bytes()).hexdigest(),
        'manifest_sha256': sha256(manifest_path.read_bytes()).hexdigest(),
        'source_hashes': {str(node_id): source['source_sha256'] for node_id, source in sources.items()},
        'human_fact_review': 'pending', 'external_transfer_authorization': 'pending',
        'online_assembly_ready': True, 'blind_test': False,
        'comparison_limit': 'frameworks differ in tool schemas, prompts and detail metadata; detail content uses frozen fragments',
        'detail_content_policy': 'same frozen fragments as retrieval; full note excluded',
    }


class RequestBlocked(RuntimeError):
    pass


class HttpBudget:
    """只在实际 transport 发送前计数；header 与凭据从不进入日志。"""

    def __init__(self, transport, *, max_requests=25):
        if type(max_requests) is not int or not 1 <= max_requests <= 25:
            raise ValueError('new request budget must be between 1 and 25')
        self.transport, self.max_requests = transport, max_requests
        self.records, self.physical_requests, self.halted = [], 0, False
        self._scope = None
        self._counts = Counter()

    @contextmanager
    def scope(self, case_id, backend):
        if case_id not in CASE_IDS or backend not in {'strict_agent', 'langchain', 'rewrite'}:
            raise ValueError('request scope outside approved profile')
        previous, self._scope = self._scope, (case_id, backend)
        try:
            yield
        finally:
            self._scope = previous

    def _block(self, reason):
        self.halted = True
        self.records.append({'status': 'blocked', 'reason': reason})
        raise RequestBlocked(reason)

    def handle_request(self, request):
        if self.halted or self._scope is None:
            self._block('halted_or_missing_scope')
        case_id, backend = self._scope
        raw = request.content
        try:
            body = raw.decode('utf-8')
            payload = json.loads(body)
        except (ValueError, UnicodeError):
            self._block('invalid_model_payload')
        if not isinstance(payload, dict):
            self._block('invalid_model_payload')
        if len(body) > 16000:
            self._block('input_chars_exceeded')
        cap = 300 if backend == 'rewrite' else 600
        if type(payload.get('max_tokens')) is not int or not 1 <= payload['max_tokens'] <= cap:
            self._block('output_tokens_exceeded')
        if self.physical_requests >= self.max_requests:
            self._block('physical_request_budget_exceeded')
        if self._counts[self._scope] >= (3 if backend == 'strict_agent' else 1):
            self._block('backend_case_budget_exceeded')
        self.physical_requests += 1
        self._counts[self._scope] += 1
        row = {'physical_request': self.physical_requests, 'case_id': case_id, 'backend': backend,
               'model': payload.get('model'), 'input_chars': len(body), 'max_output_tokens': payload['max_tokens'],
               'payload_sha256': sha256(raw).hexdigest(),
               'prompt_sha256': _hash({key: payload[key] for key in ('system', 'messages', 'tools') if key in payload}),
               'status': 'started', 'usage': None}
        self.records.append(row)
        start = perf_counter()
        try:
            response = self.transport.handle_request(request)
            response.read()
            row['http_status'] = response.status_code
            row['status'] = 'returned' if response.status_code < 400 else 'http_error'
            if response.status_code >= 400:
                self.halted = True
            try:
                usage = response.json().get('usage')
                if isinstance(usage, dict):
                    row['usage'] = {key: value if type(value) is int and value >= 0 else None
                        for key in ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
                        for value in (usage.get(key),)}
            except (ValueError, AttributeError):
                pass
            return response
        except Exception as exc:
            row.update(status='transport_error', error_type=type(exc).__name__)
            raise
        finally:
            row['latency_ms'] = round((perf_counter() - start) * 1000, 3)

    @property
    def usage_totals(self):
        sent = [row for row in self.records if 'physical_request' in row]
        keys = ('input_tokens', 'output_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens')
        if not sent or any(row['status'] != 'returned' or row['usage'] is None
                           or any(row['usage'][key] is None for key in keys) for row in sent):
            return None
        return {'input_tokens': sum(row['usage']['input_tokens'] + row['usage']['cache_read_input_tokens']
                                   + row['usage']['cache_creation_input_tokens'] for row in sent),
                'output_tokens': sum(row['usage']['output_tokens'] for row in sent)}

    def close(self):
        # 原客户 transport 归调用者所有，关闭包装器不能关闭账户原 client。
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


@contextmanager
def _isolated_application():
    """首次导入也只建临时数据路径；配置选择在授权后另行进行。"""
    expanduser = os.path.expanduser
    with TemporaryDirectory(prefix='core-rag-comparison-') as temporary, ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {
            'ENV_FILE': str(Path(temporary) / 'absent.env'), 'DATABASE_URL': 'sqlite:///:memory:',
            'AI_API_KEY': '', 'APP_ENV': 'development', 'LANGSMITH_TRACING': 'false',
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'ANONYMIZED_TELEMETRY': 'False',
            'KB_CHROMA_URL': '', 'KB_CHROMA_DIR': str(Path(temporary) / 'chroma'),
        }))
        stack.enter_context(patch.object(os.path, 'expanduser',
            lambda value: temporary if value == '~' else expanduser(value)))
        import chromadb
        stack.enter_context(patch.object(chromadb, 'PersistentClient',
            lambda *args, **kwargs: chromadb.EphemeralClient(
                settings=chromadb.Settings(anonymized_telemetry=False))))
        from app.services import agent_service, agent_tools
        from app.services.langchain_rag import run_langchain_rag
        from app.services.query_rewrite import rewrite_query
        yield agent_service, agent_tools, run_langchain_rag, rewrite_query


class _ConfiguredSDK:
    """在三个既有框架入口统一传递固定的提供方请求选项。"""

    def __init__(self, sdk):
        self._sdk = sdk

    @property
    def _client(self):
        return self._sdk._client

    @property
    def messages(self):
        return SimpleNamespace(create=self._create)

    def _create(self, **payload):
        return self._sdk.messages.create(**{**payload, 'thinking': {'type': 'disabled'}})

    def with_options(self, **options):
        return _ConfiguredSDK(self._sdk.with_options(**options))

    def close(self):
        self._sdk.close()


def load_deepseek_client(path, *, http_client=None):
    """只读取显式文件中的key，禁用dotenv插值；不查询cc-switch或应用.env。"""
    import anthropic
    from dotenv import dotenv_values

    key = dotenv_values(Path(path), interpolate=False).get('DEEPSEEK_API_KEY')
    if not isinstance(key, str) or not key.strip():
        raise ValueError('explicit DeepSeek credentials file lacks DEEPSEEK_API_KEY')
    options = {'api_key': key, 'base_url': 'https://api.deepseek.com/anthropic',
               'max_retries': 0, 'timeout': 20}
    if http_client is not None:
        options['http_client'] = http_client
    return SimpleNamespace(client=_ConfiguredSDK(anthropic.Anthropic(**options)),
                           model='deepseek-flash', source='explicit_deepseek_file', thinking='disabled')


def run_online_comparison(plan, *, allow_network=False, new_request_budget=None,
                          selected_client=None, credentials_file=None, prepare_rewrites=False):
    """授权必须先于应用导入/配置选择；测试仅注入 SDK MockTransport。"""
    if allow_network is not True or type(new_request_budget) is not int:
        raise PermissionError('explicit external-transfer authorization and new budget required')
    if not 1 <= new_request_budget <= 25:
        raise ValueError('new request budget must be between 1 and 25')
    if plan != build_dry_plan():
        raise ValueError('plan differs from current frozen development profile')
    import httpx2 as httpx
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from sqlalchemy.pool import StaticPool

    with ExitStack() as resources:
        if selected_client is None:
            if credentials_file is None:
                raise ValueError('explicit credentials file required; no default provider fallback')
            selected_client = load_deepseek_client(credentials_file)
            resources.callback(selected_client.client.close)
        agent, tools, langchain, rewrite = resources.enter_context(_isolated_application())
        from app.database import Base
        from app.models.node import KnowledgeNode
        from app.models.user import User
        if getattr(selected_client, 'client', None) is None:
            raise RuntimeError('selected Anthropic-compatible client not configured')
        original_http = selected_client.client._client
        route = getattr(original_http, '_transport_for_url', None)
        if not callable(route):
            raise TypeError('SDK HTTP transport routing unsupported; refusing unguarded call')

        class RoutedTransport:
            def handle_request(self, request):
                return route(request.url).handle_request(request)

        guard = HttpBudget(RoutedTransport(), max_requests=new_request_budget)
        guarded_http = httpx.Client(transport=guard, follow_redirects=False, trust_env=False)
        sdk = selected_client.client.with_options(max_retries=0, timeout=20, http_client=guarded_http)

        class BoundedClient:
            client = sdk
            model = selected_client.model

            def chat_with_tools(self, system, messages, tools, max_tokens=600):
                response = sdk.messages.create(model=self.model, max_tokens=min(600, max_tokens),
                    system=system, messages=messages, tools=tools)
                if response.stop_reason == 'max_tokens':
                    raise RuntimeError('provider output truncated')
                return response

            def chat(self, system, messages):
                response = sdk.messages.create(model=self.model, max_tokens=600,
                    system=system, messages=messages)
                if response.stop_reason == 'max_tokens':
                    raise RuntimeError('provider output truncated')
                return '\n'.join(block.text for block in response.content if block.type == 'text')

        bounded = BoundedClient()
        engine = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                               connect_args={'check_same_thread': False})
        corpus = load_manifest_corpus(BACKEND_ROOT / 'eval/fixtures/core-rag-corpus-20261013.json', REPOSITORY_ROOT)
        manifest = json.loads((BACKEND_ROOT / 'eval/fixtures/core-rag-corpus-20261013.json').read_text(encoding='utf-8'))
        report = {**plan, 'mode': 'online', 'physical_requests': 0, 'new_request_budget': new_request_budget,
                  'external_transfer_authorization': 'explicit invocation', 'results': [], 'rewrites': [],
                  'selected_model': selected_client.model,
                  'credential_source': getattr(selected_client, 'source', 'injected'),
                  'thinking': getattr(selected_client, 'thinking', 'provider_default')}
        try:
            Base.metadata.create_all(engine)
            with Session(engine) as db:
                db.add(User(id=1, username='frozen-eval-user', hashed_password='unused-fixture'))
                for source in manifest['documents']:
                    db.add(KnowledgeNode(id=source['node_id'], user_id=1, title=source['title'],
                                         content=corpus[source['node_id']]))
                db.commit()
                for case in plan['cases']:
                    rows = plan['frozen_retrieval'][case['case_id']]

                    def retrieval(query, *, user_id, top_k, frozen_rows=rows):
                        if user_id != 1:
                            raise ValueError('frozen retrieval owner mismatch')
                        # 查询不改变已冻结候选；不按 gold 选择或修补证据。
                        return [dict(row) for row in frozen_rows]

                    original_detail = tools.TOOL_HANDLERS['get_node_details']

                    def frozen_detail(arguments, session, *, user_id, frozen_rows=rows, handler=original_detail):
                        # 先执行原有SQL鉴权，再限定为与另一框架相同的冻结片段。
                        data = json.loads(handler(arguments, session, user_id=user_id))
                        if 'error' not in data:
                            fragments = [row['content'] for row in frozen_rows if row['node_id'] == data['id']]
                            if not fragments:
                                return json.dumps({'error': 'node outside frozen evidence'})
                            data['content'] = '\n\n'.join(fragments)
                            data['content_fragments'] = fragments
                            data['content_policy'] = 'frozen_fragments'
                        return json.dumps(data, ensure_ascii=False)

                    for backend in ('strict_agent', 'langchain'):
                        if guard.halted:
                            break
                        start = perf_counter()
                        observed = []
                        with guard.scope(case['case_id'], backend):
                            observer = lambda name, arguments, result, target=observed: target.append({
                                'tool': name, 'result_sha256': sha256(result.encode()).hexdigest()})
                            if backend == 'strict_agent':
                                # 第三次仍受同一 SDK 前预算约束，不追加隐式强制回答。
                                with (patch.object(tools, 'retrieve_relevant_nodes', retrieval),
                                      patch.dict(tools.TOOL_HANDLERS, {'get_node_details': frozen_detail}),
                                      patch.object(agent, 'MAX_ITERATIONS', 3)):
                                    result = agent.run_agent(db, SimpleNamespace(messages=[]), case['question'],
                                        user_id=1, ai_client=bounded, kb_only=True, observe_tool_result=observer,
                                        max_model_calls=3, max_input_chars=16000, max_output_tokens=600)
                            else:
                                result = langchain(db, case['question'], user_id=1, ai_client=bounded,
                                    retrieval=retrieval, observe_tool_result=observer, top_k=2,
                                    current_date='2026-10-13', max_input_chars=16000, max_output_tokens=600)
                        report['results'].append({'case_id': case['case_id'], 'backend': backend,
                            'result': result, 'observed': observed,
                            'latency_ms': round((perf_counter() - start) * 1000, 3), 'human_fact_review': 'pending'})
                # 先完成两框架对照，再消费剩余额度生成改写，避免尾部只运行一个框架。
                if prepare_rewrites:
                    for case in plan['cases']:
                        if guard.halted or guard.physical_requests >= guard.max_requests:
                            break
                        with guard.scope(case['case_id'], 'rewrite'):
                            candidate = rewrite(case['question'], enabled=True, ai_client=bounded,
                                max_input_chars=16000, max_output_tokens=300)
                        report['rewrites'].append({'case_id': case['case_id'], 'candidate': candidate,
                                                  'retrieval_gain_measured': False})
            report.update(physical_requests=guard.physical_requests, requests=guard.records,
                          usage_totals=guard.usage_totals, halted=guard.halted)
            report['rewrite_cases_not_run'] = len(plan['cases']) - len(report['rewrites']) if prepare_rewrites else 0
            return report
        finally:
            engine.dispose()
            guarded_http.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--new-request-budget', type=int)
    parser.add_argument('--credentials-file', type=Path)
    parser.add_argument('--prepare-rewrites', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args(argv)
    if args.output and (args.output.exists() or not args.output.parent.is_dir()):
        parser.error('output must be a new file in an existing directory')
    plan = build_dry_plan()
    if args.allow_network and not args.dry_run:
        if args.new_request_budget is None:
            parser.error('--allow-network requires --new-request-budget')
        if args.credentials_file is None:
            parser.error('--allow-network requires --credentials-file; no provider fallback')
        plan = run_online_comparison(plan, allow_network=True, new_request_budget=args.new_request_budget,
                                     credentials_file=args.credentials_file, prepare_rewrites=args.prepare_rewrites)
    if args.output:
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(plan, stream, ensure_ascii=False, indent=2)
    else:
        print(json.dumps({key: value for key, value in plan.items() if key != 'frozen_retrieval'},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
