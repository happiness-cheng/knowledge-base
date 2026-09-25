"""正式尾部评测：取每条长笔记最深处（最后 300 字符）的句子当 query，测 before/after。
并检测该句的 2-gram 是否与头部（char<1020）重叠，标注"独特尾"还是"共享词"。
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

SENT = re.compile(r'[^。！？!?\n]+[。！？!?]')


def grams(s):
    s = re.sub(r'\s+', '', s)
    return {s[i:i + 2] for i in range(len(s) - 1)}


def pick_deep_tail(content):
    """取最后 300 字符里的第一个完整句子；返回 (句子, 是否与头部无 2-gram 重叠)"""
    head = content[:1020]
    tail = content[-300:]
    sents = SENT.findall(tail)
    if not sents:
        return None, None
    s = sents[0].strip()
    head_grams = grams(head)
    s_grams = grams(s)
    overlap = s_grams & head_grams
    unique = len(overlap) == 0
    return s, unique


tail_q = []
for nid in sorted(short):
    d = short[nid]
    if len(d['content']) <= 1200:
        continue
    s, unique = pick_deep_tail(d['content'])
    if s:
        tail_q.append((nid, s, unique))

ext_docs = [(('ext', c['source_file'], c['chunk_index']), f"{c['chunk_title']}\n{c['content']}") for c in chunked]
before_docs = ext_docs + [(('node', nid), f"{d['title']}\n{d['content']}") for nid, d in short.items()]
after_docs = list(ext_docs)
for nid, d in short.items():
    for i, (st, sc) in enumerate(split_by_headings(d['content'])):
        after_docs.append((('note', nid, i), f"{d['title']}\n{st}\n{sc}"))

before_embs = model.encode([t for _, t in before_docs], normalize_embeddings=True, show_progress_bar=False)
after_embs = model.encode([t for _, t in after_docs], normalize_embeddings=True, show_progress_bar=False)

print(f"深尾 query 数 = {len(tail_q)}")
print("-" * 78)
b_hit = a_hit = 0
for nid, q, unique in tail_q:
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
    tag = "独特尾" if unique else "共享词"
    print(f"node={nid:2d} [{tag}] before_rank={b_rank} after_rank={a_rank} | {q[:40]}")

print("-" * 78)
print(f"深尾 recall before = {b_hit}/{len(tail_q)} = {b_hit/len(tail_q):.1%}")
print(f"深尾 recall after  = {a_hit}/{len(tail_q)} = {a_hit/len(tail_q):.1%}")
