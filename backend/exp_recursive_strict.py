"""修正递归后的正式对比：现状两级切分 vs 严格递归切分。

控制变量：同一语料 / 同模型 / 同归一化 / 同 44 条评测集 / 同 top_k=3 / 同 node 去重。
全部内存计算，不写库。
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


def run(label, sp):
    ids, texts, metas = [], [], []
    for nid, (title, content) in nodes.items():
        for i, (heading, body) in enumerate(sp(content)):
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
        ok = any(metas[i]['node_id'] == nid and metas[i]['chunk_index'] == want
                 for i in ranked)
        if ok:
            ctx += 1
        else:
            lost.append(cid)
    toks = [m['tokens'] for m in metas]
    return {
        'label': label, 'chunks': len(metas), 'median': statistics.median(toks),
        'max': max(toks), 'ge360': sum(1 for t in toks if t >= 360),
        'hit3': hit3 / n, 'mrr': mrr / n, 'ctx': ctx / n, 'lost': lost, 'n': n,
    }


rows = [run('A 现状(两级)', split_by_headings),
        run('B 严格递归', split_recursive)]

print(f'有答案用例 {rows[0]["n"]} 条\n')
print(f'{"配置":<14}{"块数":<7}{"中位tok":<9}{"最大":<7}{">=360":<7}'
      f'{"node Hit@3":<12}{"node MRR":<10}{"答案段进上下文":<12}')
print('-' * 78)
for r in rows:
    print(f'{r["label"]:<14}{r["chunks"]:<7}{r["median"]:<9.0f}{r["max"]:<7}'
          f'{r["ge360"]:<7}{r["hit3"]:<12.3f}{r["mrr"]:<10.3f}{r["ctx"]:<12.3f}')

a, b = rows
print('\n变化：')
print(f'  chunk 数      {a["chunks"]} → {b["chunks"]}')
print(f'  中位 token    {a["median"]:.0f} → {b["median"]:.0f}')
print(f'  node MRR      {a["mrr"]:.3f} → {b["mrr"]:.3f}  ({b["mrr"] - a["mrr"]:+.3f})')
print(f'  答案段进上下文 {a["ctx"]:.3f} → {b["ctx"]:.3f}  ({b["ctx"] - a["ctx"]:+.3f})')
print(f'\n  A 丢失的用例: {a["lost"]}')
print(f'  B 丢失的用例: {b["lost"]}')
print(f'  B 修好的: {sorted(set(a["lost"]) - set(b["lost"]))}')
print(f'  B 弄坏的: {sorted(set(b["lost"]) - set(a["lost"]))}')
