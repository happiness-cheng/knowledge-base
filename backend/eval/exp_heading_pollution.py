"""实验：通用小节标题是否在"稀释 / 误导"向量匹配？

## 线索（2026-10-11，S07 取证）
query「怎么保证重复请求不会重复扣款」的块级排名：
    1  node264  问答：幂等设计     0.5020
    2  node253  问答：gRPC 流控    0.4655   ← 与幂等无关
    3  node104  死锁              0.4593
    4  node212  幂等设计 ★gold     0.4592
node253 抢到第 2 名的那一块，它的 heading 是 **「问：有什么坑？」**。
而这个 heading 被 `_gen_qa_notes(260, ..., 'flat')` 生成的**9 条问答笔记共用**
（node260..267 都是「问：有什么坑？」「问：什么时候不适合用？」这类）。

## 机制假设（可证伪）
`add_node_to_index`（rag_service.py:113）把 `title\nheading\nchunk` 拼起来编码：
    '问答：gRPC 流控\n问：有什么坑？\n追问: 坑呢\n补充: ...'
"问：有什么坑？" 这个片段**本身不含任何主题信息**，却对很多 query 都有中等相似度。
当块很短（flat 问答笔记整篇塌成 1 块、只有几十字）时，
这个通用片段在**平均向量**里的权重就很大 ⇒ 向量被推向"通用问题"，而非主题。
**通用 heading 等价于给每块加了一个共享的偏置向量 b，相似度 = 主题相关度 + b·q。**

## 怎么证伪
只改**参与编码的文本**，不改切分、不改 query、不改 top_k：
    A) 现状          title + heading + chunk
    B) 去掉通用 heading  title + chunk
    C) 只去 heading    chunk（作为上界参考）
若 253 在 B 下掉出前 3、且 gold 名次不变或上升 ⇒ 假设成立，heading 在帮倒忙。
若 B/C 下所有 pattern 一起变差 ⇒ 说明 heading 整体有益，只是"通用 heading"这一子集有害，
   那就该只对**通用 heading**（在同一库里重复出现的 heading）做降权，而不是全去。

## 附带问题：heading 里"问：xxx？"这种形式对 dense 检索是好是坏
问答型笔记的 heading 是**疑问句**，与用户 query 的句式天然接近 ⇒ 句式相似会贡献分数。
这也是"句式匹配"而非"语义匹配"的一个来源。
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

spec = importlib.util.spec_from_file_location('b2', _BACKEND / 'eval' / 'bench_v2.py')
b2 = importlib.util.module_from_spec(spec)
sys.modules['b2'] = b2
spec.loader.exec_module(b2)

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
d = col.get(include=['documents', 'metadatas'])
metas, docs = d['metadatas'], d['documents']
model = rag_service._get_model()

# ---- 统计"通用 heading"：在同一库里重复出现的 heading ----
from collections import Counter  # noqa: E402
head_count = Counter(m.get('heading', '') for m in metas)
GENERIC = {h for h, c in head_count.items() if c >= 2 and h}
print('同一库里重复出现的 heading（≥2 次）:')
for h, c in head_count.most_common():
    if c >= 2 and h:
        print(f'  {c:>3} 次  {h!r}')
print()

TITLE = [m.get('title', '') for m in metas]
HEAD = [m.get('heading', '') for m in metas]
BODY = list(docs)


def encode(variant):
    if variant == 'A_title+head+body':
        texts = [f'{t}\n{h}\n{b}' if t else f'{h}\n{b}' for t, h, b in zip(TITLE, HEAD, BODY)]
    elif variant == 'B_title+body':
        texts = [f'{t}\n{b}' if t else b for t, b in zip(TITLE, BODY)]
    elif variant == 'C_body_only':
        texts = BODY
    elif variant == 'D_drop_generic_head':
        texts = [f'{t}\n{b}' if h in GENERIC else (f'{t}\n{h}\n{b}' if t else f'{h}\n{b}')
                 for t, h, b in zip(TITLE, HEAD, BODY)]
    else:
        raise ValueError(variant)
    return np.asarray(model.encode(texts, normalize_embeddings=True,
                                   show_progress_bar=False), dtype=np.float32)


TOP_K, CPN = 3, 2


def retrieve(embs, query):
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    grouped, seq = {}, []
    for idx in order:
        nid = metas[idx]['node_id']
        if len(grouped.get(nid, [])) >= CPN:
            continue
        if nid not in grouped:
            grouped[nid] = []
            seq.append(nid)
        grouped[nid].append(int(idx))
        if len(seq) >= TOP_K and all(len(grouped[x]) >= CPN for x in seq[:TOP_K]):
            break
    chosen = [i for n in seq[:TOP_K] for i in grouped[n]]
    return chosen, seq[:TOP_K]


CASES = [(c[0], c[1], c[2], c[3]) for c in b2.SYNTH_CASES]

variants = ['A_title+head+body', 'B_title+body', 'C_body_only', 'D_drop_generic_head']
embs_by = {v: encode(v) for v in variants}

print('=' * 100)
print('各变体的指标对照（同一批 27 条 query、同 top_k=3、同 chunks_per_node=2）')
print('=' * 100)
print(f'{"变体":<24}{"Hit@1":<9}{"Hit@3":<9}{"MRR":<9}{"gold块进上下文":<14}按 pattern 的"块进上下文"')
print('-' * 100)
detail = {}
for v in variants:
    rows = []
    for cid, gold, pattern, query in CASES:
        chosen, seq = retrieve(embs_by[v], query)
        nodes = [metas[i]['node_id'] for i in chosen]
        ded = []
        for n in nodes:
            if n not in ded:
                ded.append(n)
        rank = (ded.index(gold) + 1) if gold in ded else None
        rows.append({'cid': cid, 'gold': gold, 'pattern': pattern,
                     'rank': rank, 'chunk_hit': gold in nodes})
    n = len(rows)
    h1 = sum(1 for r in rows if r['rank'] == 1)
    h3 = sum(1 for r in rows if r['rank'] and r['rank'] <= 3)
    mrr = sum(1 for r in rows if r['rank']) and sum(1 / r['rank'] for r in rows if r['rank']) / n
    ch = sum(1 for r in rows if r['chunk_hit'])
    by = {}
    for r in rows:
        by.setdefault(r['pattern'], []).append(r['chunk_hit'])
    pstr = ' '.join(f'{p.replace("gen_","")[:6]}:{sum(v2)}/{len(v2)}' for p, v2 in sorted(by.items()))
    print(f'{v:<24}{h1:>3}/{n:<5}{h3:>3}/{n:<5}{mrr:<9.4f}{ch:>3}/{n} = {ch/n:.3f}   {pstr}')
    detail[v] = rows

print()
print('=' * 100)
print('S07 专项：去掉通用 heading 后，node253 还在第 2 名吗？')
print('=' * 100)
cid, gold, pattern, query = 'S07', 212, 'gen_messy', '怎么保证重复请求不会重复扣款'
for v in variants:
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs_by[v] - qv[None, :], axis=1)
    order = np.argsort(dist)
    top = [(int(i), float(1 - dist[i] ** 2 / 2)) for i in order[:6]]
    line = '  '.join(f'n{metas[i]["node_id"]}#{metas[i].get("chunk_index")}({c:.4f})'
                     for i, c in top)
    print(f'{v:<24}{line}')
