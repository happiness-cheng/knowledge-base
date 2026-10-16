"""真实业务检索的有限回答验收；默认只输出计划，不读取凭据或请求模型。"""

import argparse
import json
import os
import socket
import subprocess
import sys
import sysconfig
import time
from contextlib import ExitStack, contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import mkdtemp
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def build_profile():
    from eval.run_core_rag_comparison import build_dry_plan
    original = build_dry_plan()
    return {
        'profile': 'native-bge-http-langchain-5-development-cases',
        'cases': original['cases'], 'dataset_sha256': original['dataset_sha256'],
        'manifest_sha256': original['manifest_sha256'], 'source_hashes': original['source_hashes'],
        'physical_request_limit': 5, 'input_chars_limit': 16000, 'output_tokens_limit': 600,
        'model': 'deepseek-flash', 'endpoint': 'https://api.deepseek.com/anthropic',
        'retrieval': 'native writer/chunker -> normalized BGE -> Chroma HTTP -> SQL freshness -> actual LC prompt',
        'blind_test': False, 'query_provenance': 'source-aware agent authored; all development',
        'semantic_accuracy': None, 'human_fact_review': 'pending',
        'physical_requests': 0, 'external_transfer_authorization': 'pending',
        'does_not_evaluate': ['default Agent backend', 'reranker', 'rewrite', 'independent question generalization'],
    }


def authorize_online(allowed, budget):
    if allowed is not True:
        raise PermissionError('new explicit external-transfer authorization required')
    if type(budget) is not int or not 1 <= budget <= 5:
        raise ValueError('new physical request budget must be 1..5')


@contextmanager
def local_index(root):
    import chromadb
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    executable = Path(sysconfig.get_path('scripts')) / ('chroma.exe' if sys.platform == 'win32' else 'chroma')
    with (root / 'server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(executable), 'run', '--path', str(root / 'index'),
            '--host', '127.0.0.1', '--port', str(port)], cwd=root, env=os.environ.copy(),
            stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
        try:
            deadline = time.monotonic() + 30
            while True:
                if process.poll() is not None:
                    raise RuntimeError('temporary Chroma exited')
                try:
                    client = chromadb.HttpClient(host='127.0.0.1', port=port,
                        settings=chromadb.Settings(anonymized_telemetry=False))
                    break
                except (ValueError, OSError):
                    if time.monotonic() >= deadline:
                        raise TimeoutError('temporary Chroma startup failed') from None
                    time.sleep(.1)
            try:
                yield client
            finally:
                client.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
            # Windows venv 启动器退出与其服务子进程释放句柄之间可能存在短暂间隔。
            deadline = time.monotonic() + 3
            while True:
                with socket.socket() as probe:
                    probe.settimeout(.2)
                    listening = probe.connect_ex(('127.0.0.1', port)) == 0
                if not listening:
                    break
                if time.monotonic() >= deadline:
                    raise RuntimeError('temporary Chroma did not release its port')
                time.sleep(.05)


class RecordingSDK:
    """预检仅记录最终请求，不创建网络 transport；桩答案不计入质量指标。"""
    def __init__(self):
        self.payloads = []
        self.messages = SimpleNamespace(create=self.create)

    def with_options(self, **kwargs):
        return self

    def create(self, **payload):
        assert payload['model'] == 'deepseek-flash' and payload['max_tokens'] == 600
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > 16000:
            raise ValueError('complete payload exceeds proposed authorization')
        self.payloads.append(payload)
        return SimpleNamespace(stop_reason='end_turn', usage=None, content=[SimpleNamespace(
            type='text', text='{"status":"not_found","answer":"","source_ids":[]}')])


def run(*, model_path, hf_home, output, online=False, budget=None, credentials_file=None):
    if online:
        authorize_online(online, budget)
        if credentials_file is None:
            raise ValueError('explicit credentials file required')
    elif budget is not None or credentials_file is not None:
        raise ValueError('preflight never reads credentials or accepts a request budget')
    if output.exists():
        raise FileExistsError('evaluation requires a new report path; existing evidence is preserved')
    if not Path(model_path).is_dir() or not Path(hf_home).is_dir():
        raise ValueError('existing offline model snapshot and cache required')
    from eval.core_corpus import load_manifest_corpus, validate_core_dataset
    from eval.run_core_rag_comparison import (
        HttpBudget,
        _isolated_application,
        load_deepseek_client,
    )
    profile = build_profile()
    corpus = load_manifest_corpus(BACKEND / 'eval/fixtures/core-rag-corpus-20261013.json', BACKEND.parent)
    manifest = json.loads((BACKEND / 'eval/fixtures/core-rag-corpus-20261013.json').read_text(encoding='utf-8'))
    cases = {case.case_id: case for case in validate_core_dataset(BACKEND / 'eval/fixtures/core-rag-20261013.json', corpus)}
    report = {**profile, 'mode': 'online' if online else 'native_preflight', 'results': [],
              'model_fixture_outputs_excluded': not online, 'new_request_budget': budget,
              'harness_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'model_snapshot_revision': Path(model_path).name}
    recorder, guard = RecordingSDK(), None
    with ExitStack() as resources:
        resources.enter_context(patch.dict(os.environ, {
            'HF_HOME': str(hf_home), 'HF_HUB_CACHE': str(Path(hf_home) / 'hub'),
            'HUGGINGFACE_HUB_CACHE': str(Path(hf_home) / 'hub'),
            'HF_HUB_OFFLINE': '1', 'TRANSFORMERS_OFFLINE': '1', 'ANONYMIZED_TELEMETRY': 'False',
            'NO_PROXY': '*', 'LANGSMITH_TRACING': 'false',
            **{key: '' for key in ('HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy')},
        }))
        _agent, _tools, langchain, _rewrite = resources.enter_context(_isolated_application())
        output.parent.mkdir(parents=True, exist_ok=True)
        # 保留一次性验收状态与日志供复核，不在 Windows 句柄释放期间递归清理。
        temporary = Path(mkdtemp(prefix='native-rag-index-', dir=output.parent))
        report['retained_local_state'] = str(temporary)
        client = resources.enter_context(local_index(temporary))
        import torch
        from sentence_transformers import SentenceTransformer
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy.pool import StaticPool

        from app import database
        from app.database import Base
        from app.models.node import KnowledgeNode
        from app.models.user import User
        from app.services import rag_service as rag
        from app.utils import markdown_cleaner

        torch.set_num_threads(4)
        started = time.monotonic()
        model = SentenceTransformer(str(model_path), device='cpu', local_files_only=True)
        engine = create_engine('sqlite:///:memory:', poolclass=StaticPool,
                               connect_args={'check_same_thread': False})
        resources.callback(engine.dispose)
        sessions = sessionmaker(bind=engine)
        Base.metadata.create_all(engine)
        for target, name, value in [
            (database, 'SessionLocal', sessions), (rag, 'SessionLocal', sessions),
            (rag, 'chroma_client', client), (rag, '_SUFFIX', '_native_e2e'),
            (rag, '_embedding_model', model), (rag, '_get_tokenizer', lambda: model.tokenizer),
            (markdown_cleaner, '_get_tokenizer', lambda: model.tokenizer),
        ]:
            resources.enter_context(patch.object(target, name, value))
        with sessions() as db:
            db.add(User(id=1, username='native-rag-fixture-user', hashed_password='unused-fixture'))
            for source in manifest['documents']:
                node_id = source['node_id']
                db.add(KnowledgeNode(id=node_id, user_id=1, title=source['title'], content=corpus[node_id]))
            db.commit()
            for source in manifest['documents']:
                node_id = source['node_id']
                rag.add_node_to_index(node_id, corpus[node_id], source['title'], user_id=1)
                print(json.dumps({'indexed_node': node_id, 'elapsed_seconds': round(time.monotonic() - started, 1)}), flush=True)
            report.update(indexed_documents=len(corpus), indexed_chunks=rag._get_user_collection(1).count(),
                          indexing_seconds=round(time.monotonic() - started, 3))
            bounded = SimpleNamespace(client=recorder, model='deepseek-flash')
            if online:
                import httpx2 as httpx
                selected = load_deepseek_client(credentials_file)
                resources.callback(selected.client.close)
                route = selected.client._client._transport_for_url
                class RoutedTransport:
                    def handle_request(self, request):
                        return route(request.url).handle_request(request)
                guard = HttpBudget(RoutedTransport(), max_requests=budget)
                http = httpx.Client(transport=guard, follow_redirects=False, trust_env=False)
                resources.callback(http.close)
                sdk = selected.client.with_options(max_retries=0, timeout=20, http_client=http)
                bounded = SimpleNamespace(client=sdk, model=selected.model)
                report['external_transfer_authorization'] = 'new explicit invocation'
            try:
                for row in profile['cases']:
                    case = cases[row['case_id']]
                    if guard and (guard.halted or guard.physical_requests >= budget):
                        break
                    observed = []
                    def observer(name, arguments, result, target=observed):
                        target.append({'tool': name, 'arguments': arguments, 'result': json.loads(result)})
                    started = time.monotonic()
                    with guard.scope(case.case_id, 'langchain') if guard else ExitStack():
                        result = langchain(db, case.question, user_id=1, ai_client=bounded,
                            observe_tool_result=observer, current_date='2026-10-17',
                            max_input_chars=16000, max_output_tokens=600)
                    report['results'].append({'case_id': case.case_id, 'question': case.question,
                        'observed': observed, 'result': result, 'latency_ms': round((time.monotonic()-started)*1000, 3),
                        'human_fact_review': 'pending' if online else 'not_evaluated_mock_answer'})
                    print(json.dumps({'case_id': case.case_id, 'answer_status': result['answer_status'],
                                      'mode': report['mode']}, ensure_ascii=False), flush=True)
            finally:
                report.update(physical_requests=guard.physical_requests if guard else 0,
                    requests=guard.records if guard else [], usage_totals=guard.usage_totals if guard else None,
                    requests_prepared=len(recorder.payloads), prepared_payloads=recorder.payloads,
                    not_run=len(profile['cases'])-len(report['results']))
                output.parent.mkdir(parents=True, exist_ok=True)
                # 排他创建也防止长时间编码期间另一进程抢先写入同一路径。
                with output.open('x', encoding='utf-8') as stream:
                    stream.write(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--new-request-budget', type=int)
    parser.add_argument('--credentials-file', type=Path)
    parser.add_argument('--model-path', type=Path)
    parser.add_argument('--hf-home', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.prepare or args.allow_network:
        if not args.output or not args.model_path or not args.hf_home:
            parser.error('explicit output, offline model path and HF cache required')
        if args.prepare and args.allow_network:
            parser.error('prepare and online are mutually exclusive')
        report = run(model_path=args.model_path, hf_home=args.hf_home, output=args.output,
            online=args.allow_network, budget=args.new_request_budget, credentials_file=args.credentials_file)
        print(json.dumps({key: report.get(key) for key in (
            'mode', 'indexed_documents', 'indexed_chunks', 'physical_requests', 'requests_prepared', 'not_run')}, ensure_ascii=False))
    else:
        if args.new_request_budget is not None or args.credentials_file is not None:
            parser.error('network permission flag required before credentials or budget')
        print(json.dumps(build_profile(), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
