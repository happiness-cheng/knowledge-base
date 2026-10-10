"""块级精度分析：node 级命中太粗（一个 node 有 1~12 块，命中"这个 node"不等于命中"那段内容"）。

回答一个问题：在 node 级已命中的用例里，**gold 所在的那个 chunk** 进了 top-k 吗？
以及：实际返回的 top-k 里，有多少个 node 是"干扰项"（node 级去重后的浪费）。
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402
import importlib.util  # noqa: E402

# 复用评测集定义
spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
col = rag_service._get_user_collection(1)

# 建立 id -> (node_id, chunk_index, heading, body)
data = col.get(include=['documents', 'metadatas'])
idx_map = {}
for i, cid in enumerate(data['ids']):
    m = data['metadatas'][i]
    idx_map[cid] = (m['node_id'], m.get('chunk_index'), m.get('heading'), data['documents'][i])

print(f'集合 {col.name}：{col.count()} 块\n')
print('=' * 116)
print(f"{'ID':<6}{'gold':<6}{'期望块':<8}{'node级rank':<11}{'块级rank':<10}"
      f"实际 top5（node:chunk heading）")
print('-' * 116)

chunk_hit1 = chunk_hit3 = chunk_hit5 = 0
node_rank_ok = 0
n_cases = 0
rows = []
for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
    if nid is None:
        continue
    n_cases += 1
    chunks = split_by_headings(nodes[nid][1])
    want = ev3.verify_evidence(chunks, head, tail)

    res = rag_service.retrieve_relevant_nodes(query, top_k=5, user_id=1)
    # node 级 rank
    node_rank = next((i for i, r in enumerate(res, 1) if r['node_id'] == nid), None)
    # 块级 rank：直接查集合，看 gold chunk 的 id 排第几
    qv = rag_service.get_query_embedding(query)
    raw = col.query(query_embeddings=[qv], n_results=col.count())
    order = raw['ids'][0]
    want_id = f"{nid}:{want}" if want is not None else None
    chunk_rank = (order.index(want_id) + 1) if (want_id and want_id in order) else None

    if node_rank:
        node_rank_ok += 1
    if chunk_rank == 1:
        chunk_hit1 += 1
    if chunk_rank and chunk_rank <= 3:
        chunk_hit3 += 1
    if chunk_rank and chunk_rank <= 5:
        chunk_hit5 += 1

    top5 = ' | '.join(
        f"{idx_map[i][0]}:{idx_map[i][1]}{'' if idx_map[i][2] in (None, '') else '/' + str(idx_map[i][2])[:12]}"
        for i in order[:5])
    rows.append((cid, nid, want, node_rank, chunk_rank, query))
    print(f"{cid:<6}{nid:<6}{str(want):<8}{str(node_rank):<11}{str(chunk_rank):<10}{top5[:70]}")

print('-' * 116)
print(f'  用例 {n_cases} 条')
print(f'  node 级 Hit@3 = {node_rank_ok}/{n_cases} = {node_rank_ok / n_cases:.3f}')
print(f'  块 级 Hit@1 = {chunk_hit1}/{n_cases} = {chunk_hit1 / n_cases:.3f}')
print(f'  块 级 Hit@3 = {chunk_hit3}/{n_cases} = {chunk_hit3 / n_cases:.3f}')
print(f'  块 级 Hit@5 = {chunk_hit5}/{n_cases} = {chunk_hit5 / n_cases:.3f}')
print(f'\n  ⇒ node 级 {node_rank_ok / n_cases:.1%} vs 块级 Hit@1 {chunk_hit1 / n_cases:.1%} 的差距'
      f' = "找到对了笔记但读错了段落"的比例')
print('\n  块级 rank 最差的前 8 条:')
for cid, nid, want, nr, cr, q in sorted(rows, key=lambda r: -(r[4] or 9999))[:8]:
    print(f'    {cid} gold=node{nid} chunk={want} node_rank={nr} chunk_rank={cr}  {q[:36]}')
