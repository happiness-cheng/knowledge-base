"""T0 基线：测尾部 query 的 recall（只读实验，零改动）
复用 run_kb_eval.py 的语料（12 短笔记 + 55 chunks = 67 docs），
用生产模型 bge-large-zh-v1.5、无查询前缀（= 生产 rag_service 的真实路径）。
"""
import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np

os.environ['HF_HUB_OFFLINE'] = '1'
from sentence_transformers import SentenceTransformer

# 语料加载（与 run_kb_eval.py 一致）
short = {d['node_id']: d for d in json.load(open('corpus_short.json', encoding='utf-8'))}
chunked = json.load(open('corpus_chunked.json', encoding='utf-8'))
by_source = {}
for c in chunked:
    by_source.setdefault(c['source_file'], []).append(c)

docs = []
for nid, d in short.items():
    docs.append((('node', nid), f"{d['title']}\n{d['content']}"))
for src, chunks in by_source.items():
    for c in chunks:
        docs.append((('chunk', src, c['chunk_index']), f"{c['chunk_title']}\n{c['content']}"))

model = SentenceTransformer('BAAI/bge-large-zh-v1.5')
texts = [t for _, t in docs]
embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

TAIL = [
    (3,  "为什么需要堆内存，栈空间默认多大？"),
    (5,  "监控服务为什么用 atomic 计数器而不是互斥锁？"),
    (12, "两次握手会有什么问题，为什么还需要第三次握手？"),
    (13, "epoll 每次 wait 返回什么，为什么它比 select 快？"),
    (14, "static 类成员变量有什么特点？"),
    (16, "中国石化的扫描发现了什么信号，得分多少？"),
    (17, "#define SQUARE(x) x*x 传入 1+1 会得到什么？"),
    (18, "为什么说三次握手是数学上的最小值？"),
]

hit = 0
print(f"docs={len(docs)}  model=bge-large-zh-v1.5  prefix=False")
print("-" * 70)
for nid, q in TAIL:
    qv = model.encode([q], normalize_embeddings=True)[0]
    sims = embs @ qv
    order = np.argsort(-sims)
    rank = None
    for r, idx in enumerate(order, 1):
        key = docs[idx][0]
        if key[0] == 'node' and key[1] == nid:
            rank = r
            break
    top1 = docs[order[0]][0]
    is_hit = rank is not None and rank <= 3
    hit += is_hit
    top_sim = float(sims[order[0]])
    print(f"node={nid:2d} rank={rank} hit3={is_hit} top1={top1} sim={top_sim:.3f} | {q}")

print("-" * 70)
print(f"尾部 recall@3 = {hit}/{len(TAIL)}")
