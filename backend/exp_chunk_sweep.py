"""参数扫描：找 (上限 limit, 下界 min_tokens) 的经验最优组合。

为什么必须扫而不是拍脑袋：上界太松 → 一块塞多主题（向量被稀释）；
下界太高 → 小块被合并回去，递归白做；下界太低 → 碎块语义不完整。
这三者互相牵制，只有一个可测的最优点。实测教训（2026-10-07）：
  min=360 时递归完全失效（node1「线程同步」仍是 421 tok 含 5 个主题）
  min=0   时切出中位 64 tok 碎块，主指标掉到 0.659

评价：主指标 = "gold 段落进 LLM 上下文" 的比例；辅以 node 级 MRR 与块分布。
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
from app.utils.recursive_splitter import split_recursive  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', BASE / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

nodes = ev3.load_notes()
model = rag_service._get_model()

# 硬上限由 bge 的 512 决定，只能在"标题余量"内浮动，故固定 480 扫下界
CONFIGS = [
    ('A 现状(两级)', None, None),
    ('递归 min=0',   480, 0),
    ('递归 min=80',  480, 80),
    ('递归 min=150', 480, 150),
    ('递归 min=240', 480, 240),
    ('递归 min=360', 480, 360),
]


def build(sp, limit, min_tokens):
    ids, texts, metas = [], [], []
    for nid, (title, content) in nodes.items():
        chunks = sp(content) if limit is None else sp(content, limit, min_tokens)
        for i, (heading, body) in enumerate(chunks):
            embed_text = f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}"
            ids.append(f"{nid}:{i}")
            texts.append(embed_text)
            metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                          'tokens': _n_tokens(body), 'body': body})
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return ids, embs, metas


def evaluate(ids, embs, metas):
    per_node = {}
    for m in metas:
        per_node.setdefault(m['node_id'], []).append(m)
    n = ctx = node_hit3 = 0
    mrr = 0.0
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        chunks = [(m['heading'], m['body']) for m in per_node.get(nid, [])]
        want = ev3.verify_evidence(chunks, head, tail)
        qv = np.asarray(rag_service.get_embedding(rag_service.QUERY_PREFIX + query),
                        dtype=np.float32)
        order = np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))
        seen, ranked = set(), []
        for idx in order:
            if metas[idx]['node_id'] in seen:
                continue
            seen.add(metas[idx]['node_id'])
            ranked.append(idx)
            if len(ranked) >= 3:
                break
        nrank = next((r for r, i in enumerate(ranked, 1) if metas[i]['node_id'] == nid), None)
        if nrank:
            node_hit3 += 1
            mrr += 1 / nrank
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want for i in ranked):
            ctx += 1
    toks = [m['tokens'] for m in metas]
    return {
        'chunks': len(metas),
        'median': statistics.median(toks),
        'max': max(toks),
        'ge360': sum(1 for t in toks if t >= 360),
        'hit3': node_hit3 / n,
        'mrr': mrr / n,
        'ctx': ctx / n,
        'n': n,
    }


print(f'评测集有答案用例 {sum(1 for c in ev3.CASES if c[1] is not None)} 条')
print(f'\n{"配置":<16}{"块数":<7}{"中位tok":<9}{"最大":<7}{">=360":<7}'
      f'{"node Hit@3":<12}{"node MRR":<10}{"答案段进上下文":<14}')
print('-' * 84)
rows = []
for label, limit, mn in CONFIGS:
    if limit is None:
        ids, embs, metas = build(split_by_headings, None, None)
    else:
        ids, embs, metas = build(split_recursive, limit, mn)
    r = evaluate(ids, embs, metas)
    rows.append((label, r))
    print(f'{label:<16}{r["chunks"]:<7}{r["median"]:<9.0f}{r["max"]:<7}{r["ge360"]:<7}'
          f'{r["hit3"]:<12.3f}{r["mrr"]:<10.3f}{r["ctx"]:<14.3f}')

print('\n结论判读：')
best = max(rows, key=lambda x: (x[1]['ctx'], x[1]['mrr']))
print(f'  主指标最优：{best[0]}  答案段进上下文 {best[1]["ctx"]:.3f}  '
      f'MRR {best[1]["mrr"]:.3f}  块数 {best[1]["chunks"]}')
base = next(r for lbl, r in rows if lbl.startswith('A'))
print(f'  对照 A 现状：ctx {base["ctx"]:.3f}  MRR {base["mrr"]:.3f}  块数 {base["chunks"]}')
