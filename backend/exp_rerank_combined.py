"""补测：修好去重之后，重排还剩多少收益？（上一轮实验的设计缺陷）

## 上一轮的问题
我在"去重会把答案块丢掉"的链路上测重排，等于给重排加了天花板：
    我测的：向量召回 → **去重(丢块)** → 重排        ← 答案块已经没了，重排无从救
    标准做法：向量召回 → 重排 → 去重(按node分组)
唯一修了顺序的方案 B 只测了 1块/node，于是"重排 vs 改去重"看起来是二者选一。
**但它们不是竞争关系**：去重是 bug 修复，重排是排序优化，应该叠加。

## 本脚本补三件事
  1. 在 1/2/3 块/node 下分别测"有重排 vs 无重排"——看重排的**净增量**
  2. 候选数 N 扫描（重排线性成本，N 是可调成本旋钮）
  3. **成本优化**：greedy 分组后真正会被返回的块通常只有 top_k×cpn 块，
     其余候选的重排是浪费。测"只重排每 node 的代表块 + 少量补充"是否够用
"""
import importlib.util
import os
import statistics
import sys
import time
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

t0 = time.perf_counter()
ce = CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=512)
ce.predict([('warm', 'up')], show_progress_bar=False)
print(f'重排器加载+预热 {time.perf_counter() - t0:.1f}s\n')


def group_nodes(ordered, chunks_per_node, top_k=TOP_K):
    """按 node 分组，每 node 最多 chunks_per_node 块，返回 (下标列表, 各 node)"""
    seen, out = {}, []
    for idx in ordered:
        nid = metas[idx]['node_id']
        if seen.get(nid, 0) >= chunks_per_node:
            continue
        seen[nid] = seen.get(nid, 0) + 1
        out.append(idx)
        if len(seen) >= top_k and all(
                seen.get(metas[i]['node_id'], 0) >= chunks_per_node
                for i in out if metas[i]['node_id'] in seen):
            if len(seen) >= top_k:
                break
    return out


def run(chunks_per_node, rerank=False, cand=12, rerank_all=True):
    n = ctx = 0
    mrr = 0.0
    lat = []
    lost = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(
            [(m['heading'], m['body']) for m in per_node.get(nid, [])], head, tail)
        t0 = time.perf_counter()
        qv = np.asarray(rag_service.get_embedding(rag_service.QUERY_PREFIX + query),
                        dtype=np.float32)
        order = list(np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))[:cand])

        if rerank:
            if rerank_all:
                pool = order
            else:
                # 成本优化：只重排"每 node 的代表块"（向量分最高的那块）+ 少量补充
                pool, seen_node = [], set()
                for idx in order:
                    nn = metas[idx]['node_id']
                    if nn not in seen_node:
                        seen_node.add(nn)
                        pool.append(idx)
                    if len(pool) >= max(TOP_K * 2, 8):
                        break
            sc = ce.predict([(query, texts[i]) for i in pool],
                            show_progress_bar=False)
            reranked = [pool[j] for j in np.argsort(-np.asarray(sc))]
            rest = [i for i in order if i not in set(pool)]
            order = reranked + rest
        lat.append((time.perf_counter() - t0) * 1000)

        ranked = group_nodes(order, chunks_per_node)
        nids = [metas[i]['node_id'] for i in ranked]
        r = next((k for k, x in enumerate(nids, 1) if x == nid), None)
        if r:
            mrr += 1 / r
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want
               for i in ranked):
            ctx += 1
        else:
            lost.append(cid)
    return {'ctx': ctx / n, 'mrr': mrr / n,
            'lat': statistics.median(lat), 'lost': lost, 'n': n}


print('=== 一、去重修复后，重排的净增量 ===')
print(f'{"配置":<30}{"答案段进上下文":<14}{"node MRR":<10}{"中位延迟ms":<12}')
print('-' * 68)
res = {}
for cpn in (1, 2, 3):
    for rer in (False, True):
        key = (cpn, rer)
        label = f'{cpn}块/node + {"重排" if rer else "无重排"}'
        r = run(cpn, rer)
        res[key] = r
        print(f'{label:<30}{r["ctx"]:<14.3f}{r["mrr"]:<10.3f}{r["lat"]:<12.0f}')

print('\n重排净增量：')
for cpn in (1, 2, 3):
    a, b = res[(cpn, False)], res[(cpn, True)]
    print(f'  {cpn}块/node：{a["ctx"]:.3f} → {b["ctx"]:.3f}  '
          f'({b["ctx"] - a["ctx"]:+.3f})   延迟 {a["lat"]:.0f}→{b["lat"]:.0f}ms')

print('\n=== 二、候选数 N 扫描（2块/node + 重排）===')
print(f'{"候选数":<10}{"答案段进上下文":<14}{"中位延迟ms":<12}')
print('-' * 38)
for cand in (4, 6, 8, 12):
    r = run(2, True, cand=cand)
    print(f'N={cand:<8}{r["ctx"]:<14.3f}{r["lat"]:<12.0f}')

print('\n=== 三、成本优化：只重排"每 node 代表块" ===')
print(f'{"策略":<34}{"答案段进上下文":<14}{"中位延迟ms":<12}')
print('-' * 60)
r_all = run(2, True, cand=12, rerank_all=True)
r_rep = run(2, True, cand=12, rerank_all=False)
print(f'{"重排全部 12 个候选":<34}{r_all["ctx"]:<14.3f}{r_all["lat"]:<12.0f}')
print(f'{"只重排每node代表块(~8个)":<34}{r_rep["ctx"]:<14.3f}{r_rep["lat"]:<12.0f}')
