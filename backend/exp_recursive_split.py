"""离线控制变量实验：递归切分 vs 现有两级切分。

控制变量（除切分策略外全部锁死）：
  同一份笔记原文 / 同一 bge-large-zh-v1.5 / 同一归一化 / 同一 44 条评测集 /
  同一 top_k=3 / 同一 node 去重逻辑 / 全部在内存里算向量（不写任何集合）

指标（对齐行业标准的两层口径）：
  · node 级 Hit@3、MRR                 → "找到对的笔记"
  · chunk 级 Hit@1/3                   → "答案段排第几"
  · **答案段是否进了 LLM 上下文**       → 生产实际可用性（主指标）
  · 结构性指标：chunk 数、超限块数、heading 是否与内容一致

结构性指标为什么重要：旧实现会出现 `Collector(3)` 这种 heading 装的是 Monitor 内容的情况
（元数据与内容不符），这是"切点跨话题"的直接证据。
"""
import importlib.util
import statistics
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402
from app.utils.recursive_splitter import SOFT_LIMIT, split_recursive  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
model = rag_service._get_model()


def build(splitter):
    ids, texts, metas = [], [], []
    for nid, (title, content) in nodes.items():
        for i, (heading, body) in enumerate(splitter(content)):
            embed_text = f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}"
            ids.append(f"{nid}:{i}")
            texts.append(embed_text)
            metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                          'tokens': _n_tokens(body), 'body': body})
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return ids, embs, metas


def evaluate(name, ids, embs, metas):
    id2meta = {i: m for i, m in zip(ids, metas)}

    # gold chunk 由 evidence 在本策略产出的块里定位（避免 chunk 边界漂移）
    per_node = {}
    for i, m in zip(ids, metas):
        per_node.setdefault(m['node_id'], []).append(m)

    n = chunk_hit1 = chunk_hit3 = in_ctx = node_hit3 = 0
    mrr_sum = 0.0
    details = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(
            [(m['heading'], m['body']) for m in per_node.get(nid, [])], head, tail)

        qv = np.asarray(rag_service.get_embedding(rag_service.QUERY_PREFIX + query),
                        dtype=np.float32)
        d = np.linalg.norm(embs - qv[None, :], axis=1)
        order = np.argsort(d)

        # 全局块级 rank
        gold_id = f"{nid}:{want}" if want is not None else None
        crank = (ids.index(gold_id) + 1) if (gold_id and gold_id in ids) else None

        # node 去重 top3（复刻 retrieve_relevant_nodes 语义）
        seen, ranked = set(), []
        for idx in order:
            nid_i = metas[idx]['node_id']
            if nid_i in seen:
                continue
            seen.add(nid_i)
            ranked.append(idx)
            if len(ranked) >= 3:
                break
        nrank = next((r for r, idx in enumerate(ranked, 1) if metas[idx]['node_id'] == nid), None)
        ctx_hit = any(metas[idx]['node_id'] == nid and metas[idx]['chunk_index'] == want
                      for idx in ranked)

        if nrank:
            node_hit3 += 1
            mrr_sum += 1 / nrank
        if crank == 1:
            chunk_hit1 += 1
        if crank and crank <= 3:
            chunk_hit3 += 1
        if ctx_hit:
            in_ctx += 1
        details.append((cid, nid, want, crank, nrank, ctx_hit, query))

    toks = [m['tokens'] for m in metas]
    over = sum(1 for t in toks if t > SOFT_LIMIT)
    print(f'\n{"=" * 92}\n{name}')
    print(f'  chunk 总数 = {len(metas)}   中位 {statistics.median(toks):.0f} token   '
          f'最大 {max(toks)}   **超过 {SOFT_LIMIT} 的块 = {over}**')
    print(f'  node 级 Hit@3 = {node_hit3}/{n} = {node_hit3 / n:.3f}    MRR = {mrr_sum / n:.3f}')
    print(f'  chunk 级 Hit@1 = {chunk_hit1}/{n} = {chunk_hit1 / n:.3f}    '
          f'Hit@3 = {chunk_hit3}/{n} = {chunk_hit3 / n:.3f}')
    print(f'  **答案段进上下文 = {in_ctx}/{n} = {in_ctx / n:.3f}**   ← 主指标')
    return details, (len(metas), over, node_hit3 / n, mrr_sum / n, chunk_hit1 / n,
                     chunk_hit3 / n, in_ctx / n)


print(f'评测集 {len(ev3.CASES)} 条（有答案 {sum(1 for c in ev3.CASES if c[1] is not None)} 条）')
res = {}
for label, sp in (('A 现状（两级：## + 标点硬切）', split_by_headings),
                  ('B 递归（## → ### → 段落 → 列表 → 句子 → 硬切+overlap）', split_recursive)):
    ids, embs, metas = build(sp)
    res[label] = evaluate(label, ids, embs, metas)

labels = list(res)
da, db = res[labels[0]][0], res[labels[1]][0]
sa, sb = res[labels[0]][1], res[labels[1]][1]

print('\n' + '=' * 92)
print(f'{"指标":<26}{"A 现状":<16}{"B 递归":<16}变化')
print('-' * 92)
names = ['chunk 总数', '超过软上限的块', 'node 级 Hit@3', 'node 级 MRR',
         'chunk 级 Hit@1', 'chunk 级 Hit@3', '答案段进上下文']
for i, nm in enumerate(names):
    va, vb = sa[i], sb[i]
    if isinstance(va, float):
        print(f'{nm:<26}{va:<16.3f}{vb:<16.3f}{vb - va:+.3f}')
    else:
        print(f'{nm:<26}{va:<16}{vb:<16}{vb - va:+d}')

print('\n逐条变化（只列有变化的）:')
for x, y in zip(da, db):
    if (x[3], x[5]) != (y[3], y[5]):
        print(f'  {x[0]:<5} gold=node{x[1]:<4} 块级rank {x[3]}→{y[3]}  '
              f'进上下文 {x[5]}→{y[5]}   {x[6][:34]}')
