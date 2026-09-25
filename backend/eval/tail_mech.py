"""机械尾部 recall 对比：抽取每条长笔记的尾部句子原文当 query，测 before/after。
零手写、零泄漏，纯测「笔记自己的尾部内容（>512 token）能否被检索到」。
"""
import json
import os
import re
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np

os.environ['HF_HUB_OFFLINE'] = '1'
from sentence_transformers import SentenceTransformer
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
from app.utils.markdown_cleaner import split_by_headings

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："
short = {d['node_id']: d for d in json.load(open('corpus_short.json', encoding='utf-8'))}
chunked = json.load(open('corpus_chunked.json', encoding='utf-8'))

model = SentenceTransformer('BAAI/bge-large-zh-v1.5')

# 抽取尾部句子（char>1020，即 512 token 之外）
SENT = re.compile(r'[^。！？!?\n]+[。！？!?]')
tail_q = []
for nid in sorted(short):
    d = short[nid]
    if len(d['content']) <= 1200:
        continue
    sents = SENT.findall(d['content'][1020:])
    if sents:
        tail_q.append((nid, sents[0].strip()))

# 外部 chunks 共享
ext_docs = [(('ext', c['source_file'], c['chunk_index']), f"{c['chunk_title']}\n{c['content']}") for c in chunked]

# before：12 全文笔记；after：切分后笔记
before_docs = ext_docs + [(('node', nid), f"{d['title']}\n{d['content']}") for nid, d in short.items()]
after_docs = list(ext_docs)
for nid, d in short.items():
    for i, (st, sc) in enumerate(split_by_headings(d['content'])):
        after_docs.append((('note', nid, i), f"{d['title']}\n{st}\n{sc}"))

before_embs = model.encode([t for _, t in before_docs], normalize_embeddings=True, show_progress_bar=False)
after_embs = model.encode([t for _, t in after_docs], normalize_embeddings=True, show_progress_bar=False)

print(f"尾部 query 数 = {len(tail_q)}   before docs={len(before_docs)}   after docs={len(after_docs)}")
print("-" * 74)
b_hit = a_hit = 0
for nid, q in tail_q:
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True)[0]
    b_rank = a_rank = None
    for r, idx in enumerate(np.argsort(-(before_embs @ qv)), 1):
        k = before_docs[idx][0]
        if k[0] == 'node' and k[1] == nid:
            b_rank = r; break
    for r, idx in enumerate(np.argsort(-(after_embs @ qv)), 1):
        k = after_docs[idx][0]
        if k[0] == 'note' and k[1] == nid:
            a_rank = r; break
    b = b_rank is not None and b_rank <= 3
    a = a_rank is not None and a_rank <= 3
    b_hit += b; a_hit += a
    print(f"node={nid:2d} before_rank={b_rank} after_rank={a_rank} | {q[:46]}")

print("-" * 74)
print(f"尾部 recall before = {b_hit}/{len(tail_q)} = {b_hit/len(tail_q):.1%}")
print(f"尾部 recall after  = {a_hit}/{len(tail_q)} = {a_hit/len(tail_q):.1%}")
