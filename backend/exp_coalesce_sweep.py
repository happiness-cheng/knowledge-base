"""扫描"碎片合并阈值"：修正递归后，需要多大阈值才把碎块合回可用粒度。

固定：limit=480 / 严格递归边界链 / 同评测集 / 同模型。
变量：min_tokens（碎片合并阈值）
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


def run(label, splitter):
    ids, texts, metas = [], [], []
    for nid, (title, content) in nodes.items():
        for i, (heading, body) in enumerate(splitter(content)):
            embed_text = f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}"
            ids.append(f"{nid}:{i}")
            texts.append(embed_text)
            metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                          'tokens': _n_tokens(body), 'body': body})
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    per_node = {}
    for m in metas:
        per_node.setdefault(m['node_id'], []).append(m)

    n = ctx = hit3 = 0
    mrr = 0.0
    lost = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        n += 1
        want = ev3.verify_evidence(
            [(m['heading'], m['body']) for m in per_node.get(nid, [])], head, tail)
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
            hit3 += 1
            mrr += 1 / nrank
        if any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want for i in ranked):
            ctx += 1
        else:
            lost.append(cid)
    toks = [m['tokens'] for m in metas]
    return {'label': label, 'chunks': len(metas), 'median': statistics.median(toks),
            'ge360': sum(1 for t in toks if t >= 360), 'hit3': hit3 / n, 'mrr': mrr / n,
            'ctx': ctx / n, 'lost': lost}


configs = [('A 现状(两级)', lambda t: split_by_headings(t))]
for mn in (0, 60, 90, 120, 150, 200):
    configs.append((f'递归 min={mn}',
                    (lambda mn: lambda t: split_recursive(t, 480, mn))(mn)))

print(f'有答案用例 44 条\n')
print(f'{"配置":<16}{"块数":<7}{"中位tok":<9}{">=360":<7}{"node Hit@3":<12}'
      f'{"node MRR":<10}{"答案段进上下文":<14}')
print('-' * 80)
rows = []
for label, sp in configs:
    r = run(label, sp)
    rows.append(r)
    print(f'{label:<16}{r["chunks"]:<7}{r["median"]:<9.0f}{r["ge360"]:<7}'
          f'{r["hit3"]:<12.3f}{r["mrr"]:<10.3f}{r["ctx"]:<14.3f}')

best = max(rows, key=lambda r: (r['ctx'], r['mrr']))
base = rows[0]
print(f'\n主指标最优：{best["label"]}  ctx={best["ctx"]:.3f}  MRR={best["mrr"]:.3f}')
print(f'对照 A 现状：ctx={base["ctx"]:.3f}  MRR={base["mrr"]:.3f}  '
      f'差 {best["ctx"] - base["ctx"]:+.3f}')
print(f'\n  A 丢失: {base["lost"]}')
print(f'  最优丢失: {best["lost"]}')
print(f'  修好: {sorted(set(base["lost"]) - set(best["lost"]))}')
print(f'  弄坏: {sorted(set(best["lost"]) - set(base["lost"]))}')
