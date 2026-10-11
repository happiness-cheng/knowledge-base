"""修复前预演：用真实 20 条笔记 + 正确的 1024 维模型在**内存里**重建检索，测出修好后的指标。

## 为什么必须先做这个（不直接重建线上集合）
线上 `user_4_nodes` 是 384 维（all-MiniLM-L6-v2 时代残留），而当前代码用
bge-large-zh-v1.5（1024 维）⇒ 每次检索抛 `InvalidArgumentError`，
被 `agent_tools.py` 的 except 吞成 `{"error": "tool execution failed"}`。
**任何直接重建都会毁掉当前这份"坏但唯一"的向量**，所以先在内存里验证目标状态，
确认值得重建、且重建后指标可解释，再动线上。

## 与 baseline_live.py 的关系
baseline_live.py 走真实集合（当前因维度错误跑不出结果）；
本脚本绕过集合、直接用 MySQL 原文 + 生产切分器 + 生产模型在内存算向量，
因此不受集合状态影响，可以用来回答"修好值不值得"。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap_live as B  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

import importlib.util  # noqa: E402

import numpy as np  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.node import KnowledgeNode  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

print(B.describe())
print()

db = SessionLocal()
notes = {n.id: (n.title or '', n.content or '')
         for n in db.query(KnowledgeNode)
         .filter(KnowledgeNode.user_id == B.LIVE_USER_ID).order_by(KnowledgeNode.id).all()}
db.close()
print(f'[真实笔记] {len(notes)} 条: {sorted(notes)}')

model = rag_service._get_model()

# ---- 用生产切分器 + 生产模型在内存建索引（与 add_node_to_index 完全同构）----
ids, embs, metas = [], [], []
split_cache = {}
for nid, (title, content) in notes.items():
    chunks = split_by_headings(content)
    split_cache[nid] = chunks
    for i, (heading, chunk) in enumerate(chunks):
        embed_text = f'{title}\n{heading}\n{chunk}' if title else f'{heading}\n{chunk}'
        ids.append(f'{nid}:{i}')
        metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading, 'title': title})
        embs.append(rag_service.get_embedding(embed_text))
embs = np.asarray(embs, dtype=np.float32)
print(f'[内存索引] {len(ids)} 块，维度 {embs.shape[1]}')
norms = np.linalg.norm(embs, axis=1)
print(f'[归一化] min={norms.min():.4f} max={norms.max():.4f}  '
      f'（必须都为 1.0，否则与线上查询向量不同尺度）\n')


def retrieve(query, top_k, cpn):
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    grouped, seq = {}, []
    for idx in order:
        nid = metas[idx]['node_id']
        if len(grouped.get(nid, [])) >= cpn:
            continue
        if nid not in grouped:
            grouped[nid] = []
            seq.append(nid)
        grouped[nid].append(int(idx))
        if len(seq) >= top_k and all(len(grouped[x]) >= cpn for x in seq[:top_k]):
            break
    return [(metas[i]['node_id'], metas[i]['chunk_index']) for n in seq[:top_k]
            for i in grouped[n]]


def evaluate(top_k, cpn, label):
    n = chunk_hit = h1 = h3 = 0
    mrr = 0.0
    rows = []
    missing_gold = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        if nid not in notes:
            missing_gold.append((cid, nid))
            continue
        n += 1
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        res = retrieve(query, top_k, cpn)
        ok = (nid, want) in res
        chunk_hit += ok
        seq = []
        for a, _ in res:
            if a not in seq:
                seq.append(a)
        rank = (seq.index(nid) + 1) if nid in seq else None
        h1 += (rank == 1)
        h3 += bool(rank and rank <= 3)
        mrr += (1 / rank) if rank else 0
        rows.append({'cid': cid, 'qsrc': qsrc, 'gold': nid, 'rank': rank, 'hit': bool(ok)})
    print(f'{label}')
    print(f'  node Hit@1 {h1}/{n}  Hit@3 {h3}/{n}  MRR {mrr / n:.4f}  '
          f'**答案块进上下文 {chunk_hit}/{n} = {chunk_hit / n:.3f}**')
    if missing_gold:
        print(f'  ⚠️ gold 不属于 user_4，无法评测: {missing_gold}')
    return rows


print('=' * 100)
print('预演：真实 20 条笔记 + 1024 维正确模型（= 重建后应有的状态）')
print('=' * 100)
r3 = evaluate(3, 2, 'top_k=3 cpn=2')
print()
r5 = evaluate(5, 2, 'top_k=5 cpn=2（生产默认）')
print()
r53 = evaluate(5, 3, 'top_k=5 cpn=3')

print()
print('=== 按 query_source（生产默认 top_k=5 cpn=2）===')
for src in ('chatlog', 'personal', 'authored'):
    sub = [r for r in r5 if r['qsrc'] == src]
    if not sub:
        continue
    print(f"  {src:<10} n={len(sub):<3} Hit@1 {sum(1 for r in sub if r['rank'] == 1)}/{len(sub)}  "
          f"答案块进上下文 {sum(1 for r in sub if r['hit'])}/{len(sub)}")

print()
print('=== 未命中明细（生产默认）===')
for r in r5:
    if not r['hit']:
        print(f"  {r['cid']} [{r['qsrc']}] gold=node{r['gold']} rank={r['rank']}")

print()
print('=== 新增的 8 条笔记是否可被检索到（那 7 条从没进过任何集合）===')
NEW = [19, 21, 22, 23, 25, 26, 27, 28]
for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
    if nid not in NEW:
        continue
    want = ev3.verify_evidence(split_cache[nid], head, tail)
    res = retrieve(query, 5, 2)
    seq = []
    for a, _ in res:
        if a not in seq:
            seq.append(a)
    rank = (seq.index(nid) + 1) if nid in seq else None
    print(f"  {cid} node{nid} rank={rank} hit={(nid, want) in res}  {query[:40]}")
