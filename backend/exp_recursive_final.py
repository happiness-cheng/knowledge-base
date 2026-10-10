"""离线控制变量实验：修正后的递归切分 vs 现有两级切分。

历史（三轮迭代，全部实测，非推测）：
  第1版 递归无碎片合并        → 中位 64 tok，ctx 0.659（碎块）
  第2版 + 碎片合并(min=360)   → 与现状输出逐项相同，ctx 0.795（递归被抵消）
  第3版 严格递归（只在超长时降级，不合并）→ 中位 60 tok，ctx 0.682，净损坏 6 条
  第4版（本版）严格递归 + 碎片合并(阈值扫描) → 见下方结果

## 关键事实：本项目的现状切分已经是"结构感知"的
旧 `split_by_headings` 先按 `##` 切（含缩进容忍），这一点已覆盖了绝大多数话题边界；
本次实验测的是它**缺失的那一层**（`###` / 空行 / 列表项 / 句子的逐级降级）是否值得补。
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
            'max': max(toks), 'ge360': sum(1 for t in toks if t >= 360),
            'hit3': hit3 / n, 'mrr': mrr / n, 'ctx': ctx / n, 'lost': lost,
            'mixed': sum(1 for m in metas if m['body'].count('\n- ') >= 4)}


def fixed_size(text: str, limit: int = 480, overlap_chars: int = 120):
    """对照 C：**忽略所有语义边界**，纯固定大小 + 字符重叠。

    这是用户方案里"如果超长就用固定大小加重叠"的那一环。作为基线对照，
    用来回答：语义边界到底有没有带来收益（还是固定切也一样）。
    """
    from app.utils.markdown_cleaner import _n_tokens
    if _n_tokens(text) <= limit:
        return [('Untitled', text)]
    parts, buf = [], ''
    for line in text.split('\n'):
        cand = (buf + '\n' + line) if buf else line
        if buf and _n_tokens(cand) > limit:
            parts.append(buf)
            tail = buf[-overlap_chars:] if len(buf) > overlap_chars else ''
            buf = (tail + '\n' + line) if tail else line
        else:
            buf = cand
    if buf.strip():
        parts.append(buf)
    return [(f'Untitled({i + 1})' if i else 'Untitled', p) for i, p in enumerate(parts)]


print(f'有答案用例 44 条\n')
print(f'{"配置":<18}{"块数":<7}{"中位tok":<9}{"最大":<7}{">=360":<7}'
      f'{"node MRR":<10}{"答案段进上下文":<14}')
print('-' * 78)
rows = []
for label, sp in (('A 现状(两级+语义)', split_by_headings),
                  ('B 递归 min=150', lambda t: split_recursive(t, 480, 150)),
                  ('C 固定大小+重叠', fixed_size)):
    r = run(label, sp)
    rows.append(r)
    print(f'{label:<18}{r["chunks"]:<7}{r["median"]:<9.0f}{r["max"]:<7}{r["ge360"]:<7}'
          f'{r["mrr"]:<10.3f}{r["ctx"]:<14.3f}')

a, b, c = rows
print(f'\nA 现状  丢失: {a["lost"]}')
print(f'C 固定  丢失: {c["lost"]}')
print(f'  C 修好: {sorted(set(a["lost"]) - set(c["lost"]))}    '
      f'C 弄坏: {sorted(set(c["lost"]) - set(a["lost"]))}')
print(f'\n三方主指标：语义两级 {a["ctx"]:.3f} | 递归 {b["ctx"]:.3f} | 固定+重叠 {c["ctx"]:.3f}')
