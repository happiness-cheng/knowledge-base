"""取证：gen_messy 为什么最弱（4 条里只命中 1 条）？

## 已知事实
bench_v2 合成 cohort 27 条里 gen_messy 4 条只中 1 条，是**最差的 pattern**。
而 gen_messy 正是"复刻我真实手写笔记形态"的那类（缩进标题 + 无空行 + 口语尾巴），
所以它最差这件事必须查清 —— 否则我在真实笔记上的检索质量无从判断。

## 三个互相竞争的解释（本次要证伪/证实）
H1 **结构问题**：缩进 + 无空行让整篇塌成一个 section，多个主题混进同一块，向量被稀释。
H2 **同主题竞争**：同一主题在语料里有多份（clean / qa_clean / qa_flat），
   而 messy 版**恰好缺了 query 所问的那一节** ⇒ 检索命中别的版本是**正确的**，
   分数低是我的**语料标注问题**（gold 该指向"真正含答案的那份"）。
H3 **向量/距离问题**：messy 块本身排序就靠后（跟别的笔记比也输）。

## 怎么区分
- H1：打印 messy 笔记切出来的**块数与每块 token**，看是否塌成 1 块、是否把多主题混在一起。
  （对照：同一主题的 clean 版切成几块）
- H2：**关键词覆盖检查** —— 把 query 的特征词在**语料里所有同主题笔记**中查找，
  看 gold 里到底有没有。若含答案的是另一份 ⇒ H2 成立。
- H3：只跟**同主题**的其他版本比余弦排序，不看别的主题。
"""
import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

# 复用 bench_v2 的 SYNTH_CASES 与 nid_of（反查 node_id，不手写数字）
spec = importlib.util.spec_from_file_location('b2', _BACKEND / 'eval' / 'bench_v2.py')
b2 = importlib.util.module_from_spec(spec)
sys.modules['b2'] = b2
spec.loader.exec_module(b2)

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
d = col.get(include=['documents', 'metadatas'])
metas, docs = d['metadatas'], d['documents']
model = rag_service._get_model()

texts = []
for doc, m in zip(docs, metas):
    t, h = m.get('title', ''), m.get('heading', '')
    texts.append(f'{t}\n{h}\n{doc}' if t else f'{h}\n{doc}')
embs = np.asarray(model.encode(texts, normalize_embeddings=True,
                               show_progress_bar=False), dtype=np.float32)

# 笔记全文（按 node 聚合，保留块序）
chunks_of = {}
for cid, doc, m in zip(d['ids'], docs, metas):
    chunks_of.setdefault(m['node_id'], []).append((m.get('chunk_index'), m.get('heading'), doc))
for v in chunks_of.values():
    v.sort(key=lambda x: (x[0] is None, x[0]))

# 标题 → 所有 node（用于找"同主题的其他版本"）
by_title = {}
for nid, title, pattern, created, content in b2._ns['N']:
    by_title.setdefault(title, []).append((nid, pattern))
for nid, title, pattern, created, content in b2._ns['_generate_bulk']():
    by_title.setdefault(title, []).append((nid, pattern))


def search(query, k=5, chunks_per_node=2):
    """与 bench_v2.retrieve 同逻辑，但额外返回余弦分。"""
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    grouped, seq = {}, []
    for idx in order:
        nid = metas[idx]['node_id']
        if len(grouped.get(nid, [])) >= chunks_per_node:
            continue
        if nid not in grouped:
            grouped[nid] = []
            seq.append(nid)
        grouped[nid].append(int(idx))
        if len(seq) >= k and all(len(grouped[x]) >= chunks_per_node for x in seq[:k]):
            break
    out = []
    for nid in seq[:k]:
        for i in grouped[nid]:
            out.append((nid, i, float(1 - dist[i] ** 2 / 2)))
    return out


MESSY = [c for c in b2.SYNTH_CASES if c[2] == 'gen_messy']

print('=' * 100)
print('第 1 步：H1 结构 —— messy 笔记切成几块？（对照同主题 clean 版）')
print('=' * 100)
for cid, gold, pattern, query, note in MESSY:
    # 从元数据反查标题（不手写）
    gtitle = next(metas[i]['title'] for i in range(len(metas))
                  if metas[i]['node_id'] == gold)
    print(f'\n【{cid}】{gtitle}  node{gold}  query: {query}')
    for nid, pat in sorted(by_title.get(gtitle, [])):
        mark = ' ← gold' if nid == gold else ''
        ck = chunks_of.get(nid, [])
        print(f'    {pat:<20} node{nid:<5} {len(ck)} 块  '
              f'token={[len(c[2]) for c in ck]}{mark}')
        for idx, head, doc in ck:
            print(f'        chunk#{idx} heading={head!r} len={len(doc)}')
            print('        ' + doc[:200].replace('\n', '\n        '))
    print()

print('=' * 100)
print('第 2 步：H2 关键词覆盖 —— query 要的东西，gold 里到底有没有？')
print('=' * 100)
for cid, gold, pattern, query, note in MESSY:
    gtitle = next(metas[i]['title'] for i in range(len(metas))
                  if metas[i]['node_id'] == gold)
    gold_text = '\n'.join(doc for _, _, doc in chunks_of.get(gold, []))
    print(f'\n【{cid}】{gtitle}  query: {query}')
    print(f'  gold 全文长度 {len(gold_text)} 字（全部同主题版本长度对照）：')
    for nid, pat in sorted(by_title.get(gtitle, [])):
        txt = '\n'.join(doc for _, _, doc in chunks_of.get(nid, []))
        mark = ' ← gold' if nid == gold else ''
        print(f'    {pat:<20} node{nid:<5} {len(txt):>5} 字{mark}')
    print()

print('=' * 100)
print('第 3 步：H3 检索排序 —— messy 的块输给了谁')
print('=' * 100)
for cid, gold, pattern, query, note in MESSY:
    hits = search(query, k=3)
    gtitle = next(metas[i]['title'] for i in range(len(metas))
                  if metas[i]['node_id'] == gold)
    # gold node 里最好的块在全库排第几
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    gold_idx = [i for i in range(len(metas)) if metas[i]['node_id'] == gold]
    best = min(gold_idx, key=lambda i: dist[i])
    print(f'\n【{cid}】{gtitle}  query: {query}')
    print(f'  gold 最好的块全库排名 = {int(np.argsort(dist).tolist().index(best)) + 1}'
          f'  余弦 {1 - dist[best] ** 2 / 2:.4f}'
          f'  heading={metas[best].get("heading")!r}')
    print('  retriever top3（node 级）:')
    seen = []
    for nid, i, cos in hits:
        if nid in seen:
            continue
        seen.append(nid)
        tag = ' ← gold' if nid == gold else ''
        print(f'    node{nid:<5} {metas[i]["title"][:26]:<28} '
              f'{metas[i].get("pattern", ""):<18} cos={cos:.4f}{tag}')
    print()
