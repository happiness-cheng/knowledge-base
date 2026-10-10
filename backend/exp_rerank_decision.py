"""落地方案决策实验：在"精度"和"延迟"之间找可上线的点。

上一轮已确认：
  · 精度上 B(重排,1块) 0.955 / C(重排,2块) 0.977 / D(无重排,2块) 0.977
  · 但重排单对长块 1200ms × 12 候选 ≈ 14~20s/query → 不可上线
  · 且 max_length=64 才算"快"，而块是 480 token ⇒ 截断会丢掉保留大块的意义

本脚本测两个候选落地方案：
  方案 D2：每 node 返回 2 块，**不重排**（零新增模型、零额外延迟）
  方案 E ：廉价 Cross-Encoder（TinyBERT，4 层 14M 参数）重排，看精度是否够用

另外输出"分诊"思路的可行性数据：向量分最高的几条是否已经够用（决定要不要重排）。
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
CAND = 12
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


def rank_nodes(ordered, per_node_chunks):
    seen, out = {}, []
    for idx in ordered:
        nid = metas[idx]['node_id']
        if seen.get(nid, 0) >= per_node_chunks:
            continue
        seen[nid] = seen.get(nid, 0) + 1
        out.append(idx)
        if len(seen) >= TOP_K and all(v >= per_node_chunks for k, v in seen.items()
                                      if k in {metas[i]['node_id'] for i in out}):
            if len({metas[i]['node_id'] for i in out}) >= TOP_K:
                break
    return out


def evaluate(reranker=None, per_node_chunks=1, cand=CAND, max_len=None):
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
        if reranker is not None:
            sc = reranker.predict([(query, texts[i]) for i in order],
                                  show_progress_bar=False)
            order = [order[j] for j in np.argsort(-np.asarray(sc))]
        lat.append((time.perf_counter() - t0) * 1000)
        ranked = rank_nodes(order, per_node_chunks)
        nids = [metas[i]['node_id'] for i in ranked]
        r = next((k for k, x in enumerate(nids, 1) if x == nid), None)
        if r:
            mrr += 1 / r
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want for i in ranked):
            ctx += 1
        else:
            lost.append(cid)
    return {'hit': ctx / n, 'mrr': mrr / n, 'lat': statistics.median(lat),
            'lost': lost, 'n': n}


print(f'用例 {sum(1 for c in ev3.CASES if c[1] is not None)} 条\n')
rows = []
rows.append(('A 现状(无重排,1块)', evaluate(None, 1)))
rows.append(('D2 无重排,2块', evaluate(None, 2)))
rows.append(('D3 无重排,3块', evaluate(None, 3)))

# 廉价重排器（TinyBERT）——若本地没有则跳过
cheap = None
try:
    from sentence_transformers import CrossEncoder
    t0 = time.perf_counter()
    cheap = CrossEncoder('cross-encoder/ms-marco-TinyBERT-L-2-v2', max_length=512)
    print(f'廉价重排器加载成功 {time.perf_counter() - t0:.1f}s')
except Exception as e:
    print(f'廉价重排器不可用（{type(e).__name__}: {str(e)[:80]}）→ 跳过方案 E')

if cheap is not None:
    rows.append(('E TinyBERT重排,2块', evaluate(cheap, 2)))

print(f'{"方案":<24}{"答案段进上下文":<14}{"node MRR":<10}{"中位延迟ms":<12}')
print('-' * 62)
for label, r in rows:
    print(f'{label:<24}{r["hit"]:<14.3f}{r["mrr"]:<10.3f}{r["lat"]:<12.0f}')

base = rows[0][1]
print(f'\n参照 A 现状：hit={base["hit"]:.3f} mrr={base["mrr"]:.3f} '
      f'lat={base["lat"]:.0f}ms  丢失={base["lost"]}')
for label, r in rows[1:]:
    print(f'{label}: 修好 {sorted(set(base["lost"]) - set(r["lost"]))}  '
          f'弄坏 {sorted(set(r["lost"]) - set(base["lost"]))}')
