"""Rerank 实验：Cross-Encoder 重排对检索精度的影响。

## 为什么必须先搞清楚"重排在去重之前还是之后"
现有 `retrieve_relevant_nodes` 的顺序是：
    query → HNSW 取 top_k*3 → **按 node 去重（每 node 只留最相关的一块）** → 返回
问题：去重发生在**重排之前**，等于先扔掉了候选，再没机会救回来。
实测证据（口径 B 的 8 条失败里占 4 条）：答案在笔记的第 2 块，但被自己笔记的第 1 块挤掉。
例如 Q35「select 和 epoll 的区别」：gold=node13 块1，返回的是 13:0。

所以本实验对比三种链路：
  A 现状           候选→按node去重→返回 top3            （去重在重排前，无重排）
  B 重排→去重      候选(4倍)→**Cross-Encoder 重排**→按node去重→top3
  C 重排→多块/节点  候选(4倍)→重排→每 node 允许 2 块→top3

## Cross-Encoder 与 Bi-Encoder 的区别（本实验的核心机制）
  Bi-Encoder（bge-large-zh）：query 和文档**各自独立编码**成向量，再算余弦。
     优点：文档向量可预先算好，检索快。缺点：query 与文档从不"互相看见"，
     只能比较两个独立摘要。
  Cross-Encoder（bge-reranker）：把 **(query, 文档) 拼成一个序列**送进模型，
     逐 token 做注意力交互，直接输出相关性分数。
     优点：精度显著更高。缺点：**每对都要完整前向一次**，不能预计算
     ⇒ 只能用于对少量候选做精排，不能用于全库召回。
"""
import importlib.util
import statistics
import sys
import time
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import os  # noqa: E402
os.environ.setdefault('HF_HUB_OFFLINE', '1')      # 只用本地缓存，不联网
os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

RERANK_MODEL = 'BAAI/bge-reranker-v2-m3'
CANDIDATES = 12          # 重排候选数（bge 检索先取这么多）
TOP_K = 3                # 最终返回几个 node

nodes = ev3.load_notes()
bi = rag_service._get_model()

print(f'加载 Cross-Encoder: {RERANK_MODEL} ...')
t0 = time.perf_counter()
from sentence_transformers import CrossEncoder  # noqa: E402
ce = CrossEncoder(RERANK_MODEL, max_length=512)   # 构造参数是 max_length（属性名 max_seq_length 只是弃用别名）
print(f'  加载耗时 {time.perf_counter() - t0:.1f}s')

# ---- 建池（用现状切分，因为本轮不改切分）----
ids, texts, metas = [], [], []
for nid, (title, content) in nodes.items():
    for i, (heading, body) in enumerate(split_by_headings(content)):
        ids.append(f'{nid}:{i}')
        texts.append(f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}")
        metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                      'tokens': _n_tokens(body), 'body': body})
embs = bi.encode(texts, normalize_embeddings=True, show_progress_bar=False)
print(f'池：{len(ids)} 块')

# 预先把 gold 块号算好（按 evidence 定位，不依赖排名）
per_node = {}
for m in metas:
    per_node.setdefault(m['node_id'], []).append(m)


def pick_nodes(ordered_idx, top_k, per_node_chunks=1):
    """按 node 去重，每个 node 最多取 per_node_chunks 块。"""
    seen, out = {}, []
    for idx in ordered_idx:
        nid = metas[idx]['node_id']
        n = seen.get(nid, 0)
        if n >= per_node_chunks:
            continue
        seen[nid] = n + 1
        out.append(idx)
        if len({metas[i]['node_id'] for i in out}) >= top_k and n + 1 >= per_node_chunks:
            # 收集够 top_k 个 node 后停止
            if len(out) >= top_k * per_node_chunks:
                break
    return out


def evaluate(mode, per_node_chunks=1, use_rerank=False):
    n = ctx = hit3 = 0
    mrr = 0.0
    lost = []
    lat = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(
            [(m['heading'], m['body']) for m in per_node.get(nid, [])], head, tail)

        t0 = time.perf_counter()
        qv = np.asarray(rag_service.get_embedding(rag_service.QUERY_PREFIX + query),
                        dtype=np.float32)
        order = list(np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))[:CANDIDATES])

        if use_rerank:
            pairs = [(query, texts[i]) for i in order]
            scores = ce.predict(pairs, show_progress_bar=False)
            order = [order[j] for j in np.argsort(-np.asarray(scores))]
        lat.append((time.perf_counter() - t0) * 1000)

        ranked = pick_nodes(order, TOP_K, per_node_chunks)
        node_ids = [metas[i]['node_id'] for i in ranked]
        nrank = next((r for r, x in enumerate(node_ids, 1) if x == nid), None)
        if nrank:
            hit3 += 1
            mrr += 1 / nrank
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want for i in ranked):
            ctx += 1
        else:
            lost.append(cid)
    return {'chunks': len(ids), 'hit3': hit3 / n, 'mrr': mrr / n, 'ctx': ctx / n,
            'lost': lost, 'lat': statistics.median(lat), 'n': n}


configs = [
    ('A 现状（无重排，1块/node）', dict(use_rerank=False, per_node_chunks=1)),
    ('B 重排→去重（1块/node）', dict(use_rerank=True, per_node_chunks=1)),
    ('C 重排→去重（2块/node）', dict(use_rerank=True, per_node_chunks=2)),
    ('D 无重排（2块/node）', dict(use_rerank=False, per_node_chunks=2)),
]

print(f'\n有答案用例 {sum(1 for c in ev3.CASES if c[1] is not None)} 条，'
      f'候选 {CANDIDATES}，最终 top_k={TOP_K}\n')
print(f'{"配置":<28}{"node Hit@3":<12}{"node MRR":<10}{"答案段进上下文":<14}{"中位延迟ms":<10}')
print('-' * 76)
rows = []
for label, kw in configs:
    r = evaluate(label, **kw)
    rows.append((label, r))
    print(f'{label:<28}{r["hit3"]:<12.3f}{r["mrr"]:<10.3f}{r["ctx"]:<14.3f}{r["lat"]:<10.0f}')

a, b, c, d = rows
print(f'\nA 现状 丢失: {a[1]["lost"]}')
print(f'B 重排 丢失: {b[1]["lost"]}')
print(f'  B 修好: {sorted(set(a[1]["lost"]) - set(b[1]["lost"]))}   '
      f'B 弄坏: {sorted(set(b[1]["lost"]) - set(a[1]["lost"]))}')
print(f'C 重排+2块 丢失: {c[1]["lost"]}')
print(f'  C 修好: {sorted(set(a[1]["lost"]) - set(c[1]["lost"]))}   '
      f'C 弄坏: {sorted(set(c[1]["lost"]) - set(a[1]["lost"]))}')
print(f'\n主指标：A {a[1]["ctx"]:.3f} | B {b[1]["ctx"]:.3f} | C {c[1]["ctx"]:.3f} | D {d[1]["ctx"]:.3f}')
