"""测 Q16 的"同 node 内分差"——判断能否用"落差法"只给 Q16 开口子。

若 node5 的第 2、3 块分数几乎一样（落差很小），说明它们语义接近，
用一个"落差阈值"就能精准放行第 3 块，而不必全局提高 chunks_per_node。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

col = rag_service._get_user_collection(1)
# 需要 distance 和 metadata
data = col.get(include=['metadatas'])
meta_of = {cid: data['metadatas'][i] for i, cid in enumerate(data['ids'])}


def cos(d2):
    return 1 - d2 ** 2 / 2


print('每个有答案用例：同 node 内前 3 块的余弦分 + 第2→第3 的落差\n')
print(f'{"ID":<5}{"node":<6}{"1st":<9}{"2nd":<9}{"3rd":<9}{"落差(2nd-3rd)":<14}该node总块数')
print('-' * 78)
rows = []
for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
    if nid is None:
        continue
    qv = rag_service.get_query_embedding(query)
    res = col.query(query_embeddings=[qv], n_results=col.count())
    ids, dists = res['ids'][0], res['distances'][0]
    same = [(i, d) for i, d in zip(ids, dists)
            if meta_of[i]['node_id'] == nid]
    scores = [cos(d) for _, d in same[:3]]
    while len(scores) < 3:
        scores.append(None)
    gap = (scores[1] - scores[2]) if (scores[1] is not None and scores[2] is not None) else None
    rows.append((cid, nid, scores, gap, len(same)))
    s = lambda v: '-' if v is None else f'{v:.3f}'
    g = '-' if gap is None else f'{gap:+.3f}'
    print(f'{cid:<5}{nid:<6}{s(scores[0]):<9}{s(scores[1]):<9}{s(scores[2]):<9}{g:<14}{len(same)}')

print('\n=== 只看得 3 块及以上的 node（有"第3块"可谈的）===')
multi = [r for r in rows if r[4] >= 3 and r[3] is not None]
gaps = sorted(r[3] for r in multi)
print(f'  共 {len(multi)} 条；第2→第3 落差：min={gaps[0]:+.3f} 中位={gaps[len(gaps)//2]:+.3f} '
      f'max={gaps[-1]:+.3f}')
print('\n  落差最小的 6 条（= 第3块与第2块最接近的，落差法主要影响这些）:')
for r in sorted(multi, key=lambda x: x[3])[:6]:
    print(f"    {r[0]:<5} node{r[1]:<4} 1st={r[2][0]:.3f} 2nd={r[2][1]:.3f} 3rd={r[2][2]:.3f} "
          f"落差={r[3]:+.3f}")
print('\n  落差最大的 6 条:')
for r in sorted(multi, key=lambda x: -x[3])[:6]:
    print(f"    {r[0]:<5} node{r[1]:<4} 1st={r[2][0]:.3f} 2nd={r[2][1]:.3f} 3rd={r[2][2]:.3f} "
          f"落差={r[3]:+.3f}")
