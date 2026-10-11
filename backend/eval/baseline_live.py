"""真实在线链路评测：MySQL + user_4 + user_4_nodes（无后缀）。

## 与既有评测的唯一区别：数据源对了
`exp_online_config.py` 之类测的都是 SQLite(user 1) + `user_1_nodes_prod`（12 个 node）。
本脚本用 `_bootstrap_live`：MySQL + user_4 + `user_4_nodes`（20 个 node）——
即 GUI 真实走的链路。

要回答的问题：
1. 语料从 12 个 node 变成 20 个（+8 条 05-22 之后的笔记）后，44 条用例的指标怎么变？
   （之前只看过 12 条的那一份，语料增长的影响从未在真实数据上测过）
2. gold 用例里，有哪些在真实集合里**根本不存在** ⇒ 这些用例本身就是无效的。
3. 生产默认参数（top_k=5 / cpn=2）与我的评测参数（top_k=3）在真实语料上的差别。

注意：gold 来自 `eval_set_v3.CASES` 的 evidence 片段，**由 `verify_evidence` 程序化定位**，
不依赖 node_id 之外的手写信息；node 不存在时该用例单独标记为 `NODE_MISSING`。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap_live as B  # noqa: E402,F401  必须先于任何 app 导入

sys.stdout.reconfigure(encoding='utf-8')

import importlib.util  # noqa: E402

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

print(B.describe())
print()

# ---- 从**真实库**加载笔记（不再从 eval_set_v3.load_notes，那个写死 user_id=1）----
from app.database import SessionLocal  # noqa: E402
from app.models.node import KnowledgeNode  # noqa: E402

db = SessionLocal()
rows = (db.query(KnowledgeNode)
        .filter(KnowledgeNode.user_id == B.LIVE_USER_ID)
        .order_by(KnowledgeNode.id).all())
notes = {n.id: (n.title or '', n.content or '') for n in rows}
db.close()
print(f'[真实笔记] user_id={B.LIVE_USER_ID} 共 {len(notes)} 条: {sorted(notes)}\n')

col = rag_service._get_user_collection(B.LIVE_USER_ID)
live_nodes = sorted({m['node_id'] for m in col.get(include=['metadatas'])['metadatas']})
print(f'[真实集合] {col.name}: {col.count()} 块，node = {live_nodes}')
missing = sorted(set(notes) - set(live_nodes))
print(f'[一致性] 库里有但集合里没有的 node: {missing if missing else "无"}')
print(f'[一致性] 集合里有但库里没有的 node: '
      f'{sorted(set(live_nodes) - set(notes)) or "无"}\n')

split_cache = {nid: split_by_headings(c) for nid, (t, c) in notes.items()}


def evaluate(top_k, cpn, label):
    n = 0
    hit_chunk = 0
    h1 = h3 = 0
    mrr = 0.0
    node_missing = []
    rows_out = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        if nid not in notes:
            node_missing.append((cid, nid))
            continue
        n += 1
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        res = rag_service.retrieve_relevant_nodes(query, top_k=top_k,
                                                 user_id=B.LIVE_USER_ID,
                                                 chunks_per_node=cpn)
        ok = any(r['node_id'] == nid and r.get('chunk_index') == want for r in res)
        hit_chunk += ok
        order = []
        for r in res:
            if r['node_id'] not in order:
                order.append(r['node_id'])
        rank = (order.index(nid) + 1) if nid in order else None
        if rank == 1:
            h1 += 1
        if rank and rank <= 3:
            h3 += 1
        if rank:
            mrr += 1 / rank
        rows_out.append({'cid': cid, 'qsrc': qsrc, 'gold': nid, 'rank': rank,
                         'chunk_hit': bool(ok), 'n_chunks': len(res),
                         'chars': sum(len(r.get('content', '')) for r in res)})
    print(f'{label}')
    print(f'  node Hit@1 {h1}/{n}  Hit@3 {h3}/{n}  MRR {mrr / n:.4f}  '
          f'**答案块进上下文 {hit_chunk}/{n} = {hit_chunk / n:.3f}**  '
          f'平均块数 {sum(r["n_chunks"] for r in rows_out) / n:.2f}  '
          f'平均字符 {sum(r["chars"] for r in rows_out) / n:.0f}')
    if node_missing:
        print(f'  ⚠️ gold 在真实库里不存在，无法评测的用例 {len(node_missing)} 条: {node_missing}')
    return rows_out


print('=' * 100)
print('真实在线链路（MySQL + user_4 + user_4_nodes，20 条笔记）')
print('=' * 100)
base = evaluate(3, 2, 'top_k=3 cpn=2（既有评测用的参数，便于对照）')
print()
prod = evaluate(5, 2, 'top_k=5 cpn=2（**生产默认**，agent 不传 top_k 时就是这个）')
print()
prod3 = evaluate(5, 3, 'top_k=5 cpn=3')

print()
print('=' * 100)
print('按 query_source 分组（真实链路、生产参数 top_k=5 cpn=2）')
print('=' * 100)
for src in ('chatlog', 'personal', 'authored'):
    sub = [r for r in prod if r['qsrc'] == src]
    if not sub:
        continue
    h1 = sum(1 for r in sub if r['rank'] == 1)
    ch = sum(1 for r in sub if r['chunk_hit'])
    print(f'  {src:<10} n={len(sub):<3} Hit@1 {h1}/{len(sub)}  答案块进上下文 {ch}/{len(sub)}')

print()
print('未命中明细（生产参数）:')
for r in prod:
    if not r['chunk_hit']:
        print(f"  {r['cid']} [{r['qsrc']}] gold=node{r['gold']} rank={r['rank']}  ← 答案块没进上下文")
