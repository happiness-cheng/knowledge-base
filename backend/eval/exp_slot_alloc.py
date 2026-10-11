"""实验：改"名额分配"规则，看主指标（答案块进上下文）能不能修好 S07。

## 问题（2026-10-11 取证，非猜测）
`retrieve_relevant_nodes` 的收集逻辑是：
    按**块**距离降序扫描 → 遇到新 node 就占一个名额 → 该 node 后续块只要没满额就一并收下
后果：**一个中等相关 node 的第 2 块，会把另一个更相关 node 的第 1 块挤出上下文。**
实证 S07（query「怎么保证重复请求不会重复扣款」）：
    块级排名  1=node264(问答：幂等设计)  2=node253(问答：gRPC 流控)
             3=node104(死锁)           4=node212(幂等设计 ★gold)
    实际进 prompt  264#0 │ 253#0 │ 104#1        ← gold 一块都没进来
node253 是「问答：gRPC 流控」，与幂等无关；它按块序占住第 2 个 node 名额后，
它的第 2 块也被补齐，而这一块把 gold 顶掉。

## 另一个独立缺陷：break 条件写坏了（死循环式扫描）
    if len(order) >= top_k and all(len(grouped[n]) >= chunks_per_node for n in order[:top_k]):
        break
若前 top_k 个 node 里**任何一个**在这批 n_fetch 结果中只出现一次，
`all(...)` 恒为 False ⇒ 循环**永不 break**，会把 n_results 条全部扫完。
扫描本身不产生错误结果（多出来的都进不了 order[:top_k]），但说明这个条件
**没有表达"取够了"的意图**，是一次无效的防护。

## 本实验要回答
把分配规则换成"**全局块级贪心 + 每 node 至多 chunks_per_node 块**"，
主指标（gold 块进上下文）与 MRR 会怎么变？
  · 当前规则 = 生产行为（复刻）
  · 贪心规则 = 候选方案
两者**都不改 top_k 与 chunks_per_node**，所以上下文块数上限完全一致
（≤ top_k × chunks_per_node），是纯分配方式的对照，token 预算不变。
"""
import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

spec2 = importlib.util.spec_from_file_location('b2', _BACKEND / 'eval' / 'bench_v2.py')
b2 = importlib.util.module_from_spec(spec2)
sys.modules['b2'] = b2
spec2.loader.exec_module(b2)

TOP_K = 3
CPN = 2
N_FETCH = max(TOP_K * 3, TOP_K * CPN * 3)


def query_rows(col, query):
    """走生产同一入口取候选（含 distances），返回 (ids, dists, metas)。"""
    r = col.query(query_embeddings=[rag_service.get_query_embedding(query)],
                  n_results=N_FETCH)
    return (r['ids'][0], r['distances'][0], r['metadatas'][0])


def alloc_current(ids, dists, metas):
    """生产规则复刻。"""
    grouped, order = {}, []
    for i in range(len(ids)):
        nid = int(metas[i].get('node_id', ids[i].split(':')[0]))
        if len(grouped.get(nid, [])) >= CPN:
            continue
        if nid not in grouped:
            grouped[nid] = []
            order.append(nid)
        grouped[nid].append(i)
        if len(order) >= TOP_K and all(len(grouped[n]) >= CPN for n in order[:TOP_K]):
            break
    return order[:TOP_K], grouped


def alloc_greedy(ids, dists, metas):
    """候选规则：块级贪心，每 node 至多 CPN 块，node 数至多 TOP_K。

    与生产规则的差别：
      · 每 node 的块只收"当前全局最优"的那几块，**不无条件补齐**
        （生产的补齐会让中等相关 node 的第 2 块挤掉高相关 node）
      · 用两个预算显式控制：node 数 ≤ TOP_K，总块数 ≤ TOP_K×CPN
    """
    grouped, order = {}, []
    used_chunks = 0
    # 已按距离升序排列（col.query 的返回顺序即排序）
    for i in range(len(ids)):
        nid = int(metas[i].get('node_id', ids[i].split(':')[0]))
        if nid not in grouped:
            if len(order) >= TOP_K:
                continue          # node 名额已满，不再接纳新 node
            grouped[nid] = []
            order.append(nid)
        if len(grouped[nid]) >= CPN:
            continue
        grouped[nid].append(i)
        used_chunks += 1
        if used_chunks >= TOP_K * CPN:
            break
    return order, grouped


def evaluate(col, cases, name):
    """cases: [(cid, gold_node, query)]；按两种规则各算一遍。"""
    print('=' * 96)
    print(f'{name}  （top_k={TOP_K} chunks_per_node={CPN} n_fetch={N_FETCH}）')
    print('=' * 96)
    res = {'current': [], 'greedy': []}
    for cid, gold, query in cases:
        ids, dists, metas = query_rows(col, query)
        for rule, fn in (('current', alloc_current), ('greedy', alloc_greedy)):
            order, grouped = fn(ids, dists, metas)
            chosen = [i for n in order for i in grouped[n]]
            nodes = [int(metas[i]['node_id']) for i in chosen]
            ded = []
            for n in nodes:
                if n not in ded:
                    ded.append(n)
            rank = (ded.index(gold) + 1) if gold in ded else None
            res[rule].append({'cid': cid, 'gold': gold, 'rank': rank,
                              'chunk_hit': gold in nodes,
                              'n_nodes': len(order), 'n_chunks': len(chosen)})
    for rule in ('current', 'greedy'):
        rows = res[rule]
        n = len(rows)
        h1 = sum(1 for r in rows if r['rank'] == 1)
        h3 = sum(1 for r in rows if r['rank'] and r['rank'] <= 3)
        mrr = sum(1 / r['rank'] for r in rows if r['rank']) / n
        ch = sum(1 for r in rows if r['chunk_hit'])
        tc = sum(r['n_chunks'] for r in rows)
        print(f'  {rule:<8} node Hit@1 {h1:>3}/{n}   Hit@3 {h3:>3}/{n}   MRR {mrr:.4f}   '
              f'**gold块进上下文 {ch}/{n} = {ch / n:.4f}**   平均块数 {tc / n:.2f}')
    print()
    diff = [(a['cid'], a['rank'], b['rank']) for a, b in zip(res['current'], res['greedy'])
            if a['chunk_hit'] != b['chunk_hit'] or a['rank'] != b['rank']]
    if diff:
        print(f'  逐条差异（{len(diff)} 条）:')
        for cid, r0, r1 in diff:
            arrow = '修好' if (r0 and r1 and r1 < r0) or (not r0 and r1) else (
                '退化' if (r0 and not r1) or (r0 and r1 and r1 > r0) else '持平')
            print(f'    {cid:<6} 当前rank={str(r0):<6} 贪心rank={str(r1):<6} {arrow}')
    else:
        print('  无差异')
    return res


# ---- 合成语料（S07 在这里）----
synth = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
evaluate(synth, [(c[0], c[1], c[3]) for c in b2.SYNTH_CASES], 'COHORT B · 合成语料 27 条')

# ---- 真实语料 44 条（真实问题上的回归检查）----
prod = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_prod'))
notes = ev3.load_notes()
split_cache = {nid: split_by_headings(c) for nid, (t, c) in notes.items()}
real_cases = [(cid, nid, q) for cid, nid, ntype, qsrc, q, head, tail in ev3.CASES if nid]
evaluate(prod, real_cases, 'COHORT A · 真实笔记 44 条')
