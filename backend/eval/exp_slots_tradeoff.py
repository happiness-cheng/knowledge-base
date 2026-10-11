"""Q16 修法决策：chunks_per_node 2 vs 3 vs 4 的精度 / 成本对照。

背景：`chunks_per_node=2` 挤掉了 Q16 的 gold 块（它在 node5 内排第 3）。
实测发现"落差法"没有区分度：Q16 的第2→第3落差 +0.024 = 全库中位数，
所以按落差放行 ≈ 全局给第 3 个名额。既然如此就直接比两档，用数据决策。

指标：
  · 主指标：含 gold evidence 的块是否被返回（44 条有答案用例）
  · node MRR
  · **成本**：每次检索返回的块数 / 进 prompt 的字符数（这是真实代价）
"""
import statistics
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402
import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
split_cache = {nid: split_by_headings(c) for nid, (t, c) in nodes.items()}

print(f'{"cpn":<6}{"gold块被返回":<14}{"node MRR":<11}{"平均块数":<10}'
      f'{"平均node数":<11}{"content合计token":<17}')
print('-' * 74)
results = {}
for cpn in (1, 2, 3, 4):
    hit = 0
    n = 0
    mrr_sum = 0.0
    chunk_counts, node_counts, tok_totals = [], [], []
    # 用 top_k=3 模拟生产（agent 默认 top_k=5，这里两种都测）
    for tk in (3, 5):
        pass
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        res = rag_service.retrieve_relevant_nodes(query, top_k=3, user_id=1,
                                                 chunks_per_node=cpn)
        if any(r['node_id'] == nid and r.get('chunk_index') == want for r in res):
            hit += 1
        order, seen = [], set()
        for r in res:
            if r['node_id'] not in seen:
                seen.add(r['node_id'])
                order.append(r['node_id'])
        if nid in order:
            mrr_sum += 1 / (order.index(nid) + 1)
        chunk_counts.append(len(res))
        node_counts.append(len({r['node_id'] for r in res}))
        tok_totals.append(sum(_n_tokens(r['content']) for r in res))
    results[cpn] = (hit / n, mrr_sum / n, statistics.mean(chunk_counts),
                    statistics.mean(node_counts), statistics.mean(tok_totals))
    print(f'{cpn:<6}{f"{hit}/{n}":<14}{mrr_sum / n:<11.3f}'
          f'{statistics.mean(chunk_counts):<10.2f}{statistics.mean(node_counts):<11.2f}'
          f'{statistics.mean(tok_totals):<17.0f}')

print('\n变化（相对 cpn=2 基准）:')
base = results[2]
for cpn in (1, 3, 4):
    r = results[cpn]
    print(f'  cpn={cpn}: 主指标 {base[0]:.3f}→{r[0]:.3f} ({r[0] - base[0]:+.3f})   '
          f'MRR {base[1]:.3f}→{r[1]:.3f}   '
          f'token {base[4]:.0f}→{r[4]:.0f} ({(r[4] / base[4] - 1) * 100:+.0f}%)')

print('\n=== 同时看 agent 默认的 top_k=5（真实生产参数）===')
for cpn in (2, 3):
    hits = toks = 0
    n = 0
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        res = rag_service.retrieve_relevant_nodes(query, top_k=5, user_id=1,
                                                 chunks_per_node=cpn)
        if any(r['node_id'] == nid and r.get('chunk_index') == want for r in res):
            hits += 1
        toks += sum(_n_tokens(r['content']) for r in res)
    print(f'  cpn={cpn}: gold块被返回 {hits}/{n} = {hits / n:.3f}，'
          f'平均 content {toks / n:.0f} token/次检索')
