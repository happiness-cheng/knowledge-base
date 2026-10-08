"""knowledge-base RAG 基线 v2（2026-10-07 重建）。

为什么要重建（旧数字为何作废）：
  1. **归一化量纲变了**：旧评测 `run_kb_eval.py` 用 `normalize_embeddings=True` +
     `embs @ q`（余弦）；生产 `rag_service.get_embedding` 当时**不归一化**（norm≈18）。
     本轮已把生产也改成归一化 ⇒ 此前"评测余弦 vs 生产 L2²"两把尺子的局面结束，
     但也意味着旧结果无法与任何新结果直接对比。
  2. **旧脚本本身停在改造前**：`run_kb_eval.py:185` 仍用 all-MiniLM-L6-v2、
     传空前缀、且带 `if __name__=='__main__'` 会覆盖 baseline json。
  3. **旧评测池与"生产集合装什么"无关**：它自己在内存里建池、自己算余弦，
     从不经过 ChromaDB，所以它测不出集合内容对不对。

v2 的做法与**明确声明**：
  · 池 = `eval/corpus_short.json`（12 条短笔记）+ `eval/corpus_chunked.json`（287 块），
    共 299 —— 与旧 expanded 评测的池语义一致，因此旧数字中"同池同 query 数"的
    那对（10.7% MiniLM vs 85.7% bge+前缀）仍可作历史参考。
  · query 用 `run_kb_eval.py` 里已冻结的 28 条 CASES（含 09-09 标注修正）。
    **不另起运行时脚本**，避免"训练用一套 query、评估用另一套"的诚实性问题。
  · 目标匹配沿用旧语义：short 层按 node_id，long/external 层按 source_file（任一 chunk 命中算）。
  · 新增 NDCG@3（旧脚本只算 Recall@3 与 MRR；项目此前 grep `ndcg` 零命中）。
  · 输出 json 带明确版本号与配置快照，可复现。

⚠️ 本脚本测的是**评测语料池**（对应独立集合 user_1_nodes_eval），
   不是生产集合 user_1_nodes_prod（真实笔记 57 块）。
   生产集合的检索健康度用 `verify_prod.py` / `retrieval_health.py` 走真实读路径测。
"""
import importlib.util
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

EVAL_DIR = BASE / 'eval'
MODEL_NAME = 'BAAI/bge-large-zh-v1.5'
QUERY_PREFIX = rag_service.QUERY_PREFIX
OUT_PATH = EVAL_DIR / 'baseline_v2_bge_normalized.json'


def load_cases():
    """从冻结的 run_kb_eval.py 取 28 条 CASES（不执行其 __main__）"""
    spec = importlib.util.spec_from_file_location('_frozen_cases', EVAL_DIR / 'run_kb_eval.py')
    mod = importlib.util.module_from_spec(spec)
    sys.modules['_frozen_cases'] = mod
    spec.loader.exec_module(mod)
    return mod.CASES, mod.LAYER_OF


def build_pool():
    """文档池：(layer, key, embed_text)，key 用于命中判定"""
    short = json.loads((EVAL_DIR / 'corpus_short.json').read_text(encoding='utf-8'))
    chunked = json.loads((EVAL_DIR / 'corpus_chunked.json').read_text(encoding='utf-8'))
    docs = []
    for d in short:
        docs.append(('short', d['node_id'], f"{d['title']}\n{d['content']}"))
    for c in chunked:
        src = c['source_file']
        layer = 'long' if src.endswith(('架构.md', '说明.md', '总结.md')) else 'external'
        docs.append((layer, src, f"{c['chunk_title']}\n{c['content']}"))
    return docs


def ndcg_at_k(rank, k=3):
    """二元相关性下的 NDCG@K：命中在第 rank 位，其余为 0。

    注意（面试要点）：二元标注下 NDCG 的分辨力**来自标注分级，不来自算法**——
    这里没有分级标注，所以 NDCG@3 与 MRR 信息高度重叠，只是形式不同。真要用 NDCG
    区分"多 gold 且重要性不同"的场景，前提是标注里带 relevance 等级。
    """
    if rank is None or rank > k:
        return 0.0
    dcg = 1.0 / np.log2(rank + 1)
    idcg = 1.0 / np.log2(1 + 1)      # 最优：命中在第 1 位
    return dcg / idcg


def main():
    cases, layer_of = load_cases()
    docs = build_pool()
    model = rag_service._get_model()

    texts = [t for _, _, t in docs]
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    layers = {}
    overall = {'recall@3': 0.0, 'mrr': 0.0, 'ndcg@3': 0.0}
    details = []

    for case in cases:
        qv = np.asarray(model.encode([QUERY_PREFIX + case['query']],
                                     normalize_embeddings=True)[0], dtype=np.float32)
        order = np.argsort(-(embs @ qv))          # 余弦（已归一化，等价内积）

        best_rank = None
        for r, idx in enumerate(order, 1):
            layer, key, _ = docs[idx]
            if case['layer'] == 'short':
                if layer == 'short' and key == case['expected']:
                    best_rank = r
                    break
            elif key == case['expected']:
                best_rank = r
                break

        ly = layer_of[case['layer']]
        layers.setdefault(ly, {'n': 0, 'recall3': 0, 'mrr': 0.0, 'ndcg3': 0.0, 'details': []})
        hit3 = 1.0 if (best_rank is not None and best_rank <= 3) else 0.0
        mrr = (1.0 / best_rank) if best_rank else 0.0
        ndcg = ndcg_at_k(best_rank)
        for tgt, v in ((layers[ly], None),):
            tgt['n'] += 1
            tgt['recall3'] += hit3
            tgt['mrr'] += mrr
            tgt['ndcg3'] += ndcg
            tgt['details'].append({'id': case['id'], 'expected': case['expected'],
                                   'rank': best_rank, 'recall3': bool(hit3),
                                   'top1': f"{docs[order[0]][1]}({docs[order[0]][0]})"})
        overall['recall@3'] += hit3
        overall['mrr'] += mrr
        overall['ndcg@3'] += ndcg
        details.append((case['id'], case['layer'], case['expected'], best_rank,
                        f"{docs[order[0]][1]}({docs[order[0]][0]})"))

    n = len(cases)
    result = {
        'baseline_version': 'v2',
        'measured_at': '2026-10-07',
        'model': MODEL_NAME,
        'query_prefix': QUERY_PREFIX,
        'normalized': True,
        'distance': 'cosine (inner product on L2-normalized vectors)',
        'n_docs': len(docs),
        'n_cases': n,
        'pool': 'eval/corpus_short.json (12) + eval/corpus_chunked.json (287)',
        'note': 'pool 与 ChromaDB 无关；生产集合健康度请用 verify_prod.py',
        'recall@3': round(overall['recall@3'] / n, 4),
        'mrr': round(overall['mrr'] / n, 4),
        'ndcg@3': round(overall['ndcg@3'] / n, 4),
        'layers': {
            k: {'n': v['n'],
                'recall@3': f"{int(v['recall3'])}/{v['n']}",
                'mrr': round(v['mrr'] / v['n'], 4),
                'ndcg@3': round(v['ndcg3'] / v['n'], 4),
                'details': v['details']}
            for k, v in layers.items()
        },
    }
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

    print('=' * 74)
    print(f"RAG 基线 v2   model={MODEL_NAME}  归一化=是  度量=余弦")
    print(f"  池={len(docs)} 条   query={n} 条")
    print(f"  Recall@3 = {result['recall@3']:.3f}")
    print(f"  MRR      = {result['mrr']:.3f}")
    print(f"  NDCG@3   = {result['ndcg@3']:.3f}")
    print('-' * 74)
    for k, v in result['layers'].items():
        print(f"  {k:<8} n={v['n']:<3} Recall@3={v['recall@3']:<6} "
              f"MRR={v['mrr']:.3f}  NDCG@3={v['ndcg@3']:.3f}")
    print('-' * 74)
    print('  未进前 3 的用例（若有）:')
    miss = [d for d in details if d[3] is None or d[3] > 3]
    if miss:
        for cid, layer, exp, rank, top1 in miss:
            print(f'    {cid} [{layer}] 期望 {exp}  rank={rank}  top1={top1}')
    else:
        print('    无 —— Recall@3 = 100%，说明该指标在此池上已饱和')
    print(f'\n  已写: {OUT_PATH.name}')


if __name__ == '__main__':
    main()
