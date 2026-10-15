"""冻结语料的真实BGE切片对照及受控查询词对照；没有生成模型或业务状态。"""
import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import socket
import sys
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from eval.benchmark import file_hash
from eval.core_corpus import load_manifest_corpus, validate_core_dataset
from eval.retrieval_candidates import ChunkConfig, chunk_documents, dense_rank, reciprocal_rank_fusion
from eval.run_retrieval_matrix import _observation, _report, _snapshot, oracle_chunk_report

PREFIX = '为这个句子生成表示以用于检索相关文章：'
ALIASES = {
    'CR02': ' Redis 分布式锁 SETNX 返回值 键存在 加锁',
    'CR07': ' 进程 线程 创建 上下文切换 系统开销',
    'CR13': ' Redis 分布式锁 键过期时间 自动删除 锁超时',
    'CR19': ' 进程 线程 资源分配 独立调度 定义区别',
    'CR33': ' LRU 最近最久未使用 缓存淘汰 最后访问时间',
    'CR34': ' Docker 容器镜像 只读层 可写层',
}


def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')


class ControlledRewrite:
    """固定输出仅用于检索分支诊断，绝不假称真实LLM生成。"""
    model = 'controlled-local-fixture'

    def __init__(self, text):
        self.text = text
        self.calls = 0

    def with_options(self, **_kwargs):
        return self

    @property
    def client(self):
        return self

    @property
    def messages(self):
        return self

    def create(self, **_kwargs):
        self.calls += 1
        return SimpleNamespace(content=[SimpleNamespace(type='text', text=json.dumps({'rewrite': self.text}, ensure_ascii=False))],
                               stop_reason='end_turn', usage=None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare', action='store_true')
    parser.add_argument('--threads', type=int, default=4)
    parser.add_argument('--hf-home', type=Path, required=True, help='已有HF缓存根目录；缺失模型时禁止下载')
    args = parser.parse_args()
    cache_root = args.hf_home.resolve()
    output = Path(__file__).parent/'reports'/'slice-comparison'/datetime.now(UTC).strftime('%Y%m%dT%H%M%S%fZ')
    output.mkdir(parents=True)
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
                      HF_HOME=str(cache_root), ANONYMIZED_TELEMETRY='False')
    def no_network(*_args, **_kwargs):
        raise RuntimeError('all network disabled in native evidence experiment')
    with patch.object(socket.socket, 'connect', no_network), patch.object(socket.socket, 'connect_ex', no_network):
        from transformers import AutoTokenizer
        path, revision = _snapshot(cache_root, 'BAAI/bge-large-zh-v1.5')
        assert revision == '79e7739b6ab944e86d6171e44d24c997fc1e0116'
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)
        tokenizer.model_max_length = 10**9
        dataset_path = BACKEND/'eval/fixtures/core-rag-20261013.json'
        manifest_path = BACKEND/'eval/fixtures/core-rag-corpus-20261013.json'
        dataset = json.loads(dataset_path.read_text(encoding='utf-8'))
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        corpus = load_manifest_corpus(manifest_path, BACKEND.parent)
        cases = validate_core_dataset(dataset_path, corpus)
        details = dataset['case_metadata']
        documents = [{**row, 'user_id':1, 'content':corpus[row['node_id']]} for row in manifest['documents']]
        configs = [ChunkConfig('fixed', 480, 0), ChunkConfig('heading', 384, 0), ChunkConfig('heading', 480, 0)]
        variants = {f'{config.strategy}_{config.body_tokens}':chunk_documents(documents, tokenizer, config) for config in configs}
        plan = {'mode':'retrieval', 'model_quality_measured':False, 'retrieval_quality_measured':True,
                'dataset_sha256':file_hash(dataset_path), 'manifest_sha256':file_hash(manifest_path),
                'model_revision':revision, 'model':'BAAI/bge-large-zh-v1.5', 'device':'cpu', 'threads':args.threads,
                'context_budget':1536, 'candidate_limit':20, 'scorer':'exact normalized dense',
                'configs':[asdict(config) for config in configs], 'case_ids':[case.case_id for case in cases],
                'controlled_aliases':ALIASES, 'alias_selection':'predefined-development-only; no default tuning',
                'source_hashes':{name:file_hash(BACKEND/name) for name in ('eval/retrieval_candidates.py','eval/run_retrieval_matrix.py')},
                'harness_sha256':file_hash(Path(__file__)), 'generation_model_calls':0, 'network_requests':0,
                'all_grid_retrieval_complete':False, 'blind_test':False}
        save(output/'plan.json', plan)
        for name, chunks in variants.items():
            assert all(chunk.token_count<=512 for chunk in chunks)
            save(output/f'{name}-chunks.json', [asdict(chunk) for chunk in chunks])
        print(json.dumps({'stage':'prepared','output':str(output),'chunks':{name:len(chunks) for name,chunks in variants.items()}}), flush=True)
        if args.prepare:
            return
        import numpy as np
        import torch
        from sentence_transformers import SentenceTransformer
        torch.set_num_threads(args.threads)
        started = perf_counter()
        model = SentenceTransformer(str(path), device='cpu', local_files_only=True)
        plan['model_load_ms']=(perf_counter()-started)*1000
        from app.services.query_rewrite import rewrite_query
        accepted = {}
        for case in cases:
            if case.case_id not in ALIASES:
                continue
            assert details[case.case_id]['split']=='development'
            fixture = ControlledRewrite(case.question+ALIASES[case.case_id])
            result = rewrite_query(case.question, enabled=True, ai_client=fixture)
            assert result['accepted'] and fixture.calls==1, (case.case_id,result)
            accepted[case.case_id]=result
        save(output/'controlled-rewrites.json', accepted)
        query_texts = {case.case_id:case.question for case in cases}
        query_texts.update({f'{key}-rewrite':row['rewrite_query'] for key,row in accepted.items()})
        assert all(len(tokenizer(PREFIX+text, add_special_tokens=True)['input_ids'])<=512 for text in query_texts.values())
        started = perf_counter()
        encoded_queries = model.encode([PREFIX+text for text in query_texts.values()], normalize_embeddings=True,
                                       batch_size=8, show_progress_bar=False)
        query_ms=(perf_counter()-started)*1000
        query_vectors=dict(zip(query_texts, encoded_queries, strict=True))
        plan['shared_query_batch_ms']=query_ms
        summary = {'metadata':plan,'variants':{},'controlled_rewrite':{},'completed':False}
        for name, chunks in variants.items():
            print(json.dumps({'stage':'encoding','variant':name,'chunks':len(chunks)}), flush=True)
            started=perf_counter()
            vectors=model.encode([chunk.embedding_text for chunk in chunks], normalize_embeddings=True,
                                 batch_size=8, show_progress_bar=True)
            encoding_ms=(perf_counter()-started)*1000
            assert vectors.shape==(len(chunks),1024)
            assert np.allclose(np.linalg.norm(vectors,axis=1),1.,atol=1e-5)
            np.savez_compressed(output/f'{name}-vectors.npz', vectors=vectors)
            pools={case.case_id:dense_rank(query_vectors[case.case_id],chunks,vectors,user_id=1,limit=20) for case in cases}
            observations={case.case_id:_observation(case,pools[case.case_id],tokenizer,1536) for case in cases}
            report=_report(cases,corpus,observations,{**plan,'variant':name,'chunk_embedding_ms':encoding_ms,
                           'latency_scope':'context_pack_only; shared encoder timings separate'},details)
            save(output/f'{name}.json',report)
            summary['variants'][name]={'chunk_count':len(chunks),'max_complete_tokens':max(c.token_count for c in chunks),
                                      'embedding_ms':encoding_ms,'summary':report['summary'],'splits':report['splits'],
                                      'oracle':oracle_chunk_report(cases,chunks,details)}
            save(output/'summary.json',summary)
            print(json.dumps({'stage':'variant_complete','variant':name,'summary':report['summary']}), flush=True)
            if name=='heading_480':
                subset=[case for case in cases if case.case_id in accepted]
                for mode in ('original','rewrite_only','original_plus_rewrite'):
                    outcomes={}
                    for case in subset:
                        rewritten=dense_rank(query_vectors[f'{case.case_id}-rewrite'],chunks,vectors,user_id=1,limit=20)
                        pool=(pools[case.case_id] if mode=='original' else rewritten if mode=='rewrite_only' else
                              reciprocal_rank_fusion([pools[case.case_id],rewritten],user_id=1,k=60,limit=20))
                        outcomes[case.case_id]=_observation(case,pool,tokenizer,1536)
                    comparison=_report(subset,corpus,outcomes,{**plan,'variant':mode,'query_source':'controlled-local-fixture',
                                       'real_llm_rewrite_quality_measured':False},details)
                    save(output/f'controlled-{mode}.json',comparison)
                    summary['controlled_rewrite'][mode]={'summary':comparison['summary'],'splits':comparison['splits']}
        assert 'app.config' not in sys.modules and 'app.database' not in sys.modules
        summary['completed']=True
        save(output/'summary.json',summary)
        print(json.dumps({'stage':'complete','output':str(output),'generation_model_calls':0}), flush=True)


if __name__=='__main__':
    main()
