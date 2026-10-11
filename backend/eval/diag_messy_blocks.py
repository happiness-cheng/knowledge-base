"""取证 3：逐块看 top-10 距离，搞清楚"gold 块级排名 2 却拿不到 node 名额"。

## 为什么必须逐块看
diag_messy 里出现了一个自相矛盾的输出：
  S05「乐观锁和悲观锁什么场景用哪个」gold node210 的**最好块全库块级排名 = 2**，
  同时 retriever 的 node 级 top3 = [node262, node210, node104]（gold 排第 2）。
按 `retrieve_relevant_nodes` 的写法，取了 3 个 node 就 break，返回 order[:3]
⇒ gold 应该在返回结果里。但 bench_v2 报 S05 rank=2（未命中 top1），
而 rank=2 **仍然在 top_k 内** —— 那 bench_v2 到底怎么判失败的？

推断：bench_v2 的 rank 是"node 序列里的名次"，而**主指标要求 rank==1**。
也就是说 S05 的失败是"没排第 1"，不是"没进上下文"。这两件事的严重程度完全不同：
  · 没进上下文 → 用户拿不到答案（严重）
  · 没排第 1 → 用户照样拿到答案，只是上下文里多了一条（不严重）
本脚本把这两者**分开打印**，并给出每条用例真实进 prompt 的块清单。
"""
import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

spec = importlib.util.spec_from_file_location('b2', _BACKEND / 'eval' / 'bench_v2.py')
b2 = importlib.util.module_from_spec(spec)
sys.modules['b2'] = b2
spec.loader.exec_module(b2)

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
d = col.get(include=['documents', 'metadatas'])
metas, docs = d['metadatas'], d['documents']
model = rag_service._get_model()
texts = []
for doc, m in zip(docs, metas):
    t, h = m.get('title', ''), m.get('heading', '')
    texts.append(f'{t}\n{h}\n{doc}' if t else f'{h}\n{doc}')
embs = np.asarray(model.encode(texts, normalize_embeddings=True,
                               show_progress_bar=False), dtype=np.float32)


def blocks(query):
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    return [(int(i), float(1 - dist[i] ** 2 / 2)) for i in order]


def retriever_nodes(query, top_k=3, chunks_per_node=2):
    """逐字复刻 rag_service.retrieve_relevant_nodes 的收集逻辑，返回 node 序列。"""
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    grouped, seq = {}, []
    for idx in order:
        nid = metas[idx]['node_id']
        if len(grouped.get(nid, [])) >= chunks_per_node:
            continue
        if nid not in grouped:
            grouped[nid] = []
            seq.append(nid)
        grouped[nid].append(int(idx))
        if len(seq) >= top_k and all(len(grouped[x]) >= chunks_per_node for x in seq[:top_k]):
            break
    return seq, grouped


for cid in ('S05', 'S06', 'S07', 'S27'):
    c = next(x for x in b2.SYNTH_CASES if x[0] == cid)
    _, gold, pattern, query, _ = c
    print('=' * 100)
    print(f'{cid}  query: {query}   gold=node{gold} ({pattern})')
    print(f'{"块级#":<6}{"node":<7}{"pattern":<20}{"heading/title":<30}{"余弦":<9}标记')
    print('-' * 100)
    for k, (i, cos) in enumerate(blocks(query)[:12], 1):
        m = metas[i]
        tag = ''
        if m['node_id'] == gold:
            tag = '★gold'
        print(f'{k:<6}{m["node_id"]:<7}{m.get("pattern",""):<20}'
              f'{(m.get("heading") or "")[:28]:<30}{cos:<9.4f}{tag}')
    seq, grouped = retriever_nodes(query)
    print(f'\n  retriever 实际返回的 node 序列 = {seq}')
    print('  实际进 prompt 的块:')
    for nid in seq[:3]:
        for i in grouped[nid]:
            print(f'    node{nid} chunk#{metas[i].get("chunk_index")} '
                  f'{metas[i]["title"][:24]} ({metas[i].get("pattern","")})')
    gold_rank = (seq.index(gold) + 1) if gold in seq[:3] else None
    print(f'  ⇒ gold 是否进了 top_k 上下文: {"是" if gold_rank else "否"}'
          f'（node 序列名次 {gold_rank}）')
    if gold_rank and gold_rank > 1:
        winner = seq[0]
        print(f'  ⇒ 排名第 1 的 node{winner}：「{metas[[i for i in range(len(metas)) if metas[i]["node_id"] == winner][0]]["title"]}」')
    print()
