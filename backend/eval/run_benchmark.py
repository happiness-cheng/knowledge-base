"""统一知识库评测入口：默认离线；在线 Agent 模式需显式允许网络。"""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from unittest.mock import patch

from eval.benchmark import (
    BenchmarkObservation, evaluate, file_hash, load_cases, render_markdown,
)


class ObservedClient:
    def __init__(self, client):
        self.client = client
        self.input_tokens = 0
        self.output_tokens = 0
        self.complete_usage = True

    def chat_with_tools(self, **kwargs):
        response = self.client.chat_with_tools(**kwargs)
        usage = getattr(response, 'usage', None)
        if usage is None:
            self.complete_usage = False
        else:
            self.input_tokens += usage.input_tokens
            self.output_tokens += usage.output_tokens
        return response

    def chat(self, **kwargs):
        self.complete_usage = False
        return self.client.chat(**kwargs)


class ApplicationExecutor:
    """复用真实 run_agent，通过观察钩子记录最终送入模型的工具内容。"""
    def __init__(self, db, user_id, client=None, *, client_factory=None):
        self.db, self.user_id, self.client = db, user_id, client
        self.client_factory = client_factory
        self.invocations = []

    def __call__(self, case):
        from app.services.agent_service import run_agent
        retrieved = []
        def observe(name, arguments, raw):
            if name not in ('search_knowledge_base', 'get_node_details'):
                return
            data = json.loads(raw)
            if isinstance(data, list):
                retrieved.extend(item for item in data if isinstance(item, dict) and 'node_id' in item)
            elif isinstance(data, dict) and 'id' in data:
                retrieved.append({**data, 'node_id': data['id']})
        actual_client = self.client_factory() if self.client_factory else self.client
        self.invocations.append((case.case_id, actual_client))
        client = ObservedClient(actual_client)
        result = run_agent(self.db, SimpleNamespace(messages=[]), case.question,
                           user_id=self.user_id, ai_client=client, observe_tool_result=observe)
        answer = result['content']
        refusal_markers = ('NOT_FOUND_IN_KB', '没有找到', '无法在知识库中找到', '无法确认')
        refused = any(marker in answer for marker in refusal_markers)
        if getattr(actual_client, 'budget_exceeded', False):
            from eval.api_client import RequestBudgetExceeded
            raise RequestBudgetExceeded('agent_request_budget_exceeded')
        if answer.startswith(('Error:', 'Agent encountered an error:')) or answer == '[No response]':
            raise RuntimeError('agent_provider_error')
        totals = getattr(actual_client, 'usage_totals', None)
        return BenchmarkObservation(
            retrieved=retrieved, answer=answer, citations=result['source_ids'], refused=refused,
            input_tokens=totals['input_tokens'] if totals is not None else client.input_tokens if client.complete_usage else None,
            output_tokens=totals['output_tokens'] if totals is not None else client.output_tokens if client.complete_usage else None,
            steps=result['steps'],
        )


class FixtureClient:
    """只依工具返回内容回答的确定性模型桩，绝不读取 case gold 或评分结果。"""
    def chat_with_tools(self, **kwargs):
        messages = kwargs['messages']
        last = messages[-1]['content']
        if isinstance(last, str):
            blocks = [SimpleNamespace(type='tool_use', name='search_knowledge_base',
                        input={'query': last, 'top_k': 3}, id='fixture-search')]
        else:
            results = json.loads(last[0]['content'])
            if results:
                first = results[0]
                text = f"{first['content']} [doc:{first['node_id']}]"
            else:
                text = 'NOT_FOUND_IN_KB：无法在知识库中找到答案。'
            blocks = [SimpleNamespace(type='text', text=text)]
        return SimpleNamespace(content=blocks, usage=SimpleNamespace(input_tokens=10, output_tokens=5))


def _revision():
    result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, text=True, check=False)
    return result.stdout.strip() if result.returncode == 0 else 'unavailable'


def _offline(cases, nodes):
    # 启动前阻止加载真实 .env、管理员凭据和生产 Chroma；实际 loop 和工具执行仍被调用。
    import builtins
    import chromadb
    backend = Path(__file__).resolve().parent.parent
    os.environ.update(ENV_FILE=str(backend / '.env.offline-not-present'), DATABASE_URL='sqlite:///:memory:',
                      AI_API_KEY='', APP_ENV='development', KB_CHROMA_SUFFIX='_benchmark_fixture',
                      HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', NO_PROXY='localhost,127.0.0.1',
                      KB_CHROMA_URL='')
    original_read, original_open = Path.read_text, builtins.open
    def guarded_read(path, *a, **kw):
        return '' if path.resolve() == backend / '.env' else original_read(path, *a, **kw)
    def guarded_open(path, *a, **kw):
        if isinstance(path, (str, os.PathLike)) and Path(path).resolve() == Path.home() / '.claude/settings.json':
            raise FileNotFoundError('offline benchmark excludes administrator credentials')
        return original_open(path, *a, **kw)
    client = chromadb.EphemeralClient(settings=chromadb.Settings(anonymized_telemetry=False))
    with patch.object(chromadb, 'PersistentClient', lambda **kw: client), patch.object(
        Path, 'read_text', guarded_read
    ), patch('builtins.open', guarded_open):
        from app.services import agent_tools
        from app.services import agent_service  # noqa: F401
    def fixture_retrieve(query, top_k=3, user_id=1):
        # 可公开的人造 fixture 词匹配；不是 embedding / ANN 质量测试。
        words = set(re.findall(r'[\w]+', query.lower()))
        ranked = [(len(words & set(re.findall(r'[\w]+', node['content'].lower()))), node)
                  for node in nodes]
        ranked.sort(key=lambda pair: (-pair[0], pair[1]['node_id']))
        return [{**node, 'note_date': '', 'kb_latest_date': ''} for score, node in ranked[:top_k] if score]
    with patch.object(agent_tools, 'retrieve_relevant_nodes', fixture_retrieve):
        return evaluate(cases, {node['node_id']: node['content'] for node in nodes},
                        ApplicationExecutor(None, 1, FixtureClient()), {})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    default = Path(__file__).resolve().parent / 'fixtures' / 'benchmark.json'
    parser.add_argument('--dataset', type=Path, default=default)
    parser.add_argument('--corpus', type=Path)
    parser.add_argument('--mode', choices=['offline-fixture', 'retrieval', 'agent'], default='offline-fixture')
    parser.add_argument('--user-id', type=int)
    parser.add_argument('--suffix', default='')
    parser.add_argument('--chroma-dir', type=Path)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--allow-network', action='store_true')
    parser.add_argument('--output', type=Path, default=Path('eval/reports/benchmark'))
    args = parser.parse_args(argv)
    if not 1 <= args.top_k <= 10:
        parser.error('top-k must be between 1 and 10')
    if args.mode == 'agent' and not args.allow_network:
        parser.error('agent mode requires explicit --allow-network and approval of data/cost')
    if args.mode != 'offline-fixture' and (args.user_id is None or args.user_id < 1 or args.chroma_dir is None):
        parser.error('real retrieval requires explicit --user-id and --chroma-dir')
    corpus_path = args.corpus or args.dataset
    document = json.loads(corpus_path.read_text(encoding='utf-8'))
    nodes = document['nodes']
    if len({node['node_id'] for node in nodes}) != len(nodes):
        parser.error('duplicate corpus node id')
    cases = load_cases(args.dataset)
    metadata = {'mode': args.mode, 'dataset_hash': file_hash(args.dataset),
                'corpus_hash': file_hash(corpus_path), 'git_sha': _revision(),
                'measured_at': datetime.now(timezone.utc).isoformat(),
                'corpus_nodes': len(nodes), 'refusal_rule': 'explicit markers; strict legacy metric additionally requires no citation; manual review required',
                'source': 'artificial_fixture' if args.mode == 'offline-fixture' else 'explicit_snapshot'}
    backend = Path(__file__).resolve().parent.parent
    metadata['application_hashes'] = {name: file_hash(backend / name) for name in (
        'app/services/agent_service.py', 'app/services/agent_tools.py',
        'app/services/rag_service.py', 'eval/benchmark.py', 'eval/run_benchmark.py')}
    if args.mode == 'offline-fixture':
        report = _offline(cases, nodes)
        metadata.update(model='deterministic_fixture', embedding='fixture_word_overlap',
                        retrieval='stub', user_id=1, top_k=3, model_quality_measured=False)
    else:
        # 本地检索默认禁止隐式下载 embedding；缺少模型缓存时明确失败。
        if not args.allow_network:
            os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        import chromadb
        os.environ['KB_CHROMA_SUFFIX'] = args.suffix
        client = chromadb.PersistentClient(path=str(args.chroma_dir.resolve()),
            settings=chromadb.Settings(anonymized_telemetry=False))
        from app.services import index_store
        # 本地诊断显式指定了目录，不能因服务环境变量而查询另一个索引。
        with patch.object(index_store, 'create_index_client', lambda *a, **kw: client):
            from app.services import rag_service
        collection = client.get_collection(name=rag_service.get_collection_name(args.user_id))
        from app.database import SessionLocal
        from app.models.node import KnowledgeNode
        db = SessionLocal()
        try:
            actual = {node.id: node.content for node in db.query(KnowledgeNode).filter(
                KnowledgeNode.user_id == args.user_id).all()}
            if actual != {node['node_id']: node['content'] for node in nodes}:
                parser.error('corpus snapshot differs from selected application user; export an exact snapshot first')
            metadata.update(user_id=args.user_id, collection=collection.name, chunk_count=collection.count(),
                            embedding='BAAI/bge-large-zh-v1.5', normalization=True, top_k=args.top_k,
                            chunks_per_node=rag_service.MAX_CHUNKS_PER_NODE,
                            query_prefix=rag_service.QUERY_PREFIX, distance=collection.metadata or {'hnsw:space': 'l2'})
            if args.mode == 'retrieval':
                executor = lambda case: BenchmarkObservation(retrieved=rag_service.retrieve_relevant_nodes(
                    case.question, top_k=args.top_k, user_id=args.user_id))
                metadata['model_quality_measured'] = False
            else:
                from app.services.claude_client import get_client_for_user
                from app.models.user import User
                user = db.query(User).filter(User.id == args.user_id).one()
                ai_client = get_client_for_user(user)
                executor = ApplicationExecutor(db, args.user_id, ai_client)
                metadata.update(model=ai_client.model, top_k='agent_tool_argument',
                                real_model_called=True, model_quality_measured=False)
            report = evaluate(cases, actual, executor, metadata)
        finally:
            db.close()
    report['metadata'] = metadata
    args.output.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    json_path = args.output / f'{args.mode}-{stamp}.json'
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    json_path.with_suffix('.md').write_text(render_markdown(report), encoding='utf-8')
    print(json.dumps({'mode': args.mode, 'summary': report['summary'], 'report': str(json_path)}, ensure_ascii=False))
    return int(report['summary']['execution_errors'] > 0 or report['summary']['invalid_cases'] > 0)


if __name__ == '__main__':
    raise SystemExit(main())
