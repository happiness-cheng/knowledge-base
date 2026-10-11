"""Q16 定位：gold 块在**所属 node 内部**的排名，以及各 node 的"块数需求"分布。

## 背景
`chunks_per_node=2`（每 node 最多返回 2 块）把 Q16 的 gold 块挤掉了：
Q16 期望 node5 的「Queue」块，但 node5 有 8 块，只给了 2 个名额。
修法候选：
  A 提高 chunks_per_node（简单，但 prompt 线性变长）
  B 按**分数落差**动态决定：同一 node 内，高分块若紧跟着次高分块，就一起带上
  C 按节点优先级分配名额（第 1 名给更多块）

选哪个取决于数据：gold 块在 node 内的排名、以及"同 node 内相邻块的分差"有多大。
"""
import json
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
col = rag_service._get_user_collection(1)
data = col.get(include=['metadatas', 'documents'])
# id -> (node_id, chunk_index)
meta_of = {cid: (data['metadatas'][i]['node_id'], data['metadatas'][i].get('chunk_index'))
           for i, cid in enumerate(data['ids'])}

print('=== 每个 node 的块数（决定"名额"够不够）===')
per_node_count = {}
for nid, _ in meta_of.values():
    per_node_count[nid] = per_node_count.get(nid, 0) + 1
for nid in sorted(per_node_count):
    title = nodes[nid][0]
    print(f'  node{nid:<3} {per_node_count[nid]:>2} 块   {title[:30]}')

print('\n=== 有答案用例：gold 块在所属 node 内部的排名 ===')
print(f'{"ID":<5}{"gold":<6}{"node内排名":<11}{"全库排名":<10}{"该node块数":<11}'
      f'{"node内相邻分差":<14}')
rank_in_node_dist = {}
need_more = []
for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
    if nid is None:
        continue
    chunks = split_by_headings(nodes[nid][1])
    want = ev3.verify_evidence(chunks, head, tail)
    if want is None:
        continue
    qv = rag_service.get_query_embedding(query)
    ids = col.query(query_embeddings=[qv], n_results=col.count())['ids'][0]
    # 该 node 的块在全局顺序里的位置
    same = [i for i in ids if meta_of[i][0] == nid]
    if f'{nid}:{want}' not in same:
        continue
    in_node = same.index(f'{nid}:{want}') + 1
    global_rank = ids.index(f'{nid}:{want}') + 1
    rank_in_node_dist[in_node] = rank_in_node_dist.get(in_node, 0) + 1
    if in_node > 2:
        need_more.append(cid)
    # node 内相邻块的距离差（用于评估"落差法"是否可行）
    dists = []
    for i in same[:4]:
        idx = data['ids'].index(i)
        # 需要 distance：重新查一次拿距离
        pass
    print(f'{cid:<5}{nid:<6}{in_node:<11}{global_rank:<10}{len(same):<11}')

print('\n=== gold 在 node 内排名的分布 ===')
for k in sorted(rank_in_node_dist):
    print(f'  第 {k} 位: {rank_in_node_dist[k]} 条')
print(f'\n  ⇒ gold 排在 node 内第 3 位及以后的用例：{sorted(set(need_more))}')
print(f'  ⇒ 这些就是"chunks_per_node=2 挤掉"的用例，需要第 3 个名额')
