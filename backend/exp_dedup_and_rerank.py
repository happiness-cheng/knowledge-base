"""回答两个问题的定向实验：
  Q1 重排为什么"看起来效果不佳"？—— 是不是去重造成的
  Q2 去重到底在防什么？—— 用数字展示"不去重"的代价

四个配置，每个只跑一遍（Cross-Encoder 结果按 (query,chunk) 缓存，避免重复前向）：
  A  去重(1块/node) 无重排   = 旧生产行为
  B  去重(1块/node) 有重排   = 上一轮的"重排"方案
  C  去重(2块/node) 无重排   = 已落地的修复
  D  去重(2块/node) 有重排   = 修复+重排的叠加（上一轮漏测的）
  E  **不去重** 有重排       = 看去重的代价有多大

另外统计"长笔记霸榜"现象：不去重时 top3 里 node 的重复度。
"""
import importlib.util
import os
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('HF_HUB_OFFLINE', '1')
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
bi = rag_service._get_model()
TOP_K = 3
CAND = 12

ids, texts, metas = [], [], []
for nid, (title, content) in nodes.items():
    for i, (heading, body) in enumerate(split_by_headings(content)):
        ids.append(f'{nid}:{i}')
        texts.append(f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}")
        metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                      'body': body, 'tokens': _n_tokens(body)})
embs = bi.encode(texts, normalize_embeddings=True, show_progress_bar=False)
per_node = {}
for m in metas:
    per_node.setdefault(m['node_id'], []).append(m)

from sentence_transformers import CrossEncoder  # noqa: E402

print('加载重排器...')
ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)
ce.predict([('warm', 'up')], show_progress_bar=False)

# ---- 预先把所有 (query, 候选块) 的向量序算好，重排结果缓存 ----
cache: dict[tuple, float] = {}


def rerank_scores(query: str, idxs: list[int]) -> list[float]:
    todo = [(i, (query, texts[i])) for i in idxs if (query, i) not in cache]
    if todo:
        sc = ce.predict([p for _, p in todo], show_progress_bar=False)
        for (i, _), s in zip(todo, sc):
            cache[(query, i)] = float(s)
    return [cache[(query, i)] for i in idxs]


def run(rerank=False, chunks_per_node=1, dedup=True):
    n = ctx = 0
    mrr = 0.0
    lat = []
    lost = []
    fanout = []                 # 不去重时 top3 里 node 的重复度
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(
            [(m['heading'], m['body']) for m in per_node.get(nid, [])], head, tail)
        t0 = time.perf_counter()
        qv = np.asarray(rag_service.get_embedding(rag_service.QUERY_PREFIX + query),
                        dtype=np.float32)
        order = list(np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))[:CAND])
        if rerank:
            sc = rerank_scores(query, order)
            order = [order[j] for j in np.argsort(-np.asarray(sc))]
        lat.append((time.perf_counter() - t0) * 1000)

        if not dedup:
            ranked = order[:TOP_K]
        else:
            seen, ranked = {}, []
            for idx in order:
                nn = metas[idx]['node_id']
                if seen.get(nn, 0) >= chunks_per_node:
                    continue
                seen[nn] = seen.get(nn, 0) + 1
                ranked.append(idx)
                if len(seen) >= TOP_K and all(v >= chunks_per_node
                                              for v in list(seen.values())[:TOP_K]):
                    break
        fanout.append(len(set(metas[i]['node_id'] for i in ranked)))

        nids = [metas[i]['node_id'] for i in ranked]
        r = next((k for k, x in enumerate(nids, 1) if x == nid), None)
        if r:
            mrr += 1 / r
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want
               for i in ranked):
            ctx += 1
        else:
            lost.append(cid)
    return {'ctx': ctx / n, 'mrr': mrr / n, 'lat': statistics.median(lat),
            'lost': lost, 'n': n, 'fanout': statistics.mean(fanout)}


configs = [
    ('A 1块/node 无重排（旧生产）', dict(rerank=False, chunks_per_node=1)),
    ('B 1块/node 有重排（上轮方案）', dict(rerank=True, chunks_per_node=1)),
    ('C 2块/node 无重排（已落地）', dict(rerank=False, chunks_per_node=2)),
    ('D 2块/node 有重排（上轮漏测）', dict(rerank=True, chunks_per_node=2)),
    ('E 不去重 有重排', dict(rerank=True, dedup=False)),
]

# 支持命令行只跑指定配置：重排是 CPU 瓶颈，分批跑可以早拿到关键结论
#   用法：python exp_dedup_and_rerank.py D E      只跑 D、E
only = [a.upper() for a in sys.argv[1:]]
if only:
    configs = [c for c in configs if c[0][0].upper() in only]

print(f'\n用例 {sum(1 for c in ev3.CASES if c[1] is not None)} 条，候选 {CAND}，'
      f'top_k={TOP_K}；本次跑 {len(configs)} 个配置\n')
print(f'{"配置":<30}{"答案段进上下文":<14}{"node MRR":<10}{"top3里平均node数":<16}')
print('-' * 72)
res = {}
for label, kw in configs:
    t0 = time.perf_counter()
    r = run(**kw)
    res[label] = r
    print(f'{label:<30}{r["ctx"]:<14.3f}{r["mrr"]:<10.3f}{r["fanout"]:<16.2f}'
          f'  ({time.perf_counter() - t0:.0f}s)', flush=True)

print('\n=== 回答 Q1：去掉"去重 bug"后，重排的净增量 ===')
Q1 = (('A 1块/node 无重排（旧生产）', 'B 1块/node 有重排（上轮方案）'),
      ('C 2块/node 无重排（已落地）', 'D 2块/node 有重排（上轮漏测）'))
for a, b in Q1:
    if a not in res or b not in res:
        continue
    ra, rb = res[a], res[b]
    print(f'  {a[:14]} → {b[:14]} : {ra["ctx"]:.3f} → {rb["ctx"]:.3f} '
          f'({rb["ctx"] - ra["ctx"]:+.3f})')

D, E = 'D 2块/node 有重排（上轮漏测）', 'E 不去重 有重排'
if D in res and E in res:
    print('\n=== 回答 Q2：不去重的代价（E vs D）===')
    d, e = res[D], res[E]
    print(f'  去重(2块/node) : ctx={d["ctx"]:.3f}  top3 平均覆盖 {d["fanout"]:.2f} 个不同 node')
    print(f'  不去重         : ctx={e["ctx"]:.3f}  top3 平均覆盖 {e["fanout"]:.2f} 个不同 node')
    print(f'  ⇒ 不去重时 top3 平均只有 {e["fanout"]:.2f} 个不同 node（= 长笔记霸榜程度）')
    print(f'  ⇒ 去重把覆盖度从 {e["fanout"]:.2f} 提到 {d["fanout"]:.2f}')

print('\n各配置丢失用例:')
for label, r in res.items():
    print(f'  {label[:26]:<28} {r["lost"]}')
