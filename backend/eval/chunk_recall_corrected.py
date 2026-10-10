"""修正上一轮的判读：区分三种"块级"口径，避免把全局排名误读成检索失败。

口径 A（上一轮用的）：gold chunk 在**全库**按距离排第几       → 全局精度，但不是生产行为
口径 B（生产实际）：retrieve_relevant_nodes 按 node 去重后返回的 top-3 里，
                    gold chunk 是否就在其中           → **LLM 到底看不看得到答案段**
口径 C：返回的那 3 个 node 里，gold node 自己的最好块是不是 gold chunk（"代表块选对没"）
"""
import importlib.util
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
col = rag_service._get_user_collection(1)
data = col.get(include=['documents', 'metadatas'])
meta_of = {cid: (data['metadatas'][i]['node_id'], data['metadatas'][i].get('chunk_index'),
                 data['metadatas'][i].get('heading'))
           for i, cid in enumerate(data['ids'])}

print(f'集合 {col.name}  {col.count()} 块\n')
print('=' * 112)
print(f"{'ID':<6}{'gold':<6}{'期望块':<8}{'A 全局rank':<12}{'B 是否在返回集':<16}"
      f"{'C 代表块=gold块':<16}返回的 3 个 node:chunk")
print('-' * 112)

in_context = 0
rep_ok = 0
n = 0
rows = []
for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
    if nid is None:
        continue
    n += 1
    chunks = split_by_headings(nodes[nid][1])
    want = ev3.verify_evidence(chunks, head, tail)
    want_id = f"{nid}:{want}" if want is not None else None

    # 口径 A
    qv = rag_service.get_query_embedding(query)
    order = col.query(query_embeddings=[qv], n_results=col.count())['ids'][0]
    a_rank = (order.index(want_id) + 1) if (want_id and want_id in order) else None

    # 口径 B/C：走生产函数
    res = rag_service.retrieve_relevant_nodes(query, top_k=3, user_id=1)
    b_hit = any(r['node_id'] == nid and r.get('chunk_index') == want for r in res)
    gold_node_res = next((r for r in res if r['node_id'] == nid), None)
    c_ok = bool(gold_node_res and gold_node_res.get('chunk_index') == want)
    if b_hit:
        in_context += 1
    if c_ok:
        rep_ok += 1
    ret = ' | '.join(f"{r['node_id']}:{r.get('chunk_index')}" for r in res)
    rows.append((cid, nid, want, a_rank, b_hit, c_ok, query, ret))
    print(f"{cid:<6}{nid:<6}{str(want):<8}{str(a_rank):<12}"
          f"{('是 ✅' if b_hit else '否 ❌'):<16}{('是' if c_ok else '否'):<16}{ret}")

print('-' * 112)
print(f'  用例 {n} 条')
print(f'  口径 A 全局块级 Hit@1      = {sum(1 for r in rows if r[3] == 1)}/{n}')
print(f'  口径 B 答案段进了 LLM 上下文 = {in_context}/{n} = {in_context / n:.3f}   ← **这才是关键指标**')
print(f'  口径 C gold node 的代表块选对 = {rep_ok}/{n} = {rep_ok / n:.3f}')
print('\n  口径 B 失败的用例（答案段没进上下文）:')
bad = [r for r in rows if not r[4]]
for cid, nid, want, ar, bh, cok, q, ret in bad:
    print(f'    {cid} gold=node{nid} 期望块={want} 全局rank={ar}  返回={ret}')
    print(f'         {q}')
if not bad:
    print('    无 —— 所有答案段都进了 LLM 上下文')
