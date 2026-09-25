"""整体 recall 混合评测：头部 query + 尾部 query，零重词纪律。
复用 tail_baseline 的语料（12 短笔记 + 287 chunks = 299 docs），
生产模型 bge-large-zh-v1.5、无查询前缀（= 生产真实路径）。
"""
import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np

os.environ['HF_HUB_OFFLINE'] = '1'
from sentence_transformers import SentenceTransformer

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

# (position, target_node_id, query) —— 尾部 query 严格零重词（不含标题词）
CASES = [
    ('head', 1,  "一个程序里同时跑多个执行流，在地址空间和调度开销上有什么差别？"),
    ('head', 2,  "需要随机访问和尾部增删，与需要中间频繁插入的两种结构，各选什么？"),
    ('head', 7,  "网址变成 https 之后，数据传输时多了什么安全处理？"),
    ('head', 8,  "后进先出和先进先出的两种结构，各自用在什么场景？"),
    ('head', 3,  "左值引用和右值引用，分别绑定什么、用在什么场合？"),
    ('head', 5,  "监听端口收连接的模块，怎么避免业务处理阻塞新连接的接收？"),
    ('head', 12, "建立连接时 SYN 和 ACK 两个标志位，分别表示什么意思？"),
    ('head', 13, "一个线程同时监控多个文件描述符，这种技术解决什么问题？"),
    ('tail', 3,  "程序运行时内存分成哪几个区域，哪个区域默认很小且大小必须编译期确定？"),
    ('tail', 5,  "一个独立 HTTP 服务暴露指标给外部抓取，为什么用无锁计数器而不是互斥锁？"),
    ('tail', 12, "两台机器建立可靠连接，为什么消息来回两趟不够、四趟又多余？"),
    ('tail', 13, "同时监控上万个网络连接，为什么有的做法每次都把所有连接交给内核全量扫描很浪费？"),
    ('tail', 14, "类的所有对象共享同一个计数值，这种成员变量叫什么？"),
    ('tail', 18, "要确认两台机器彼此的收发能力，最少需要几趟消息、为什么？"),
]

res = {'head': [0, 0], 'tail': [0, 0]}
print(f"docs={len(docs)}  model=bge-large-zh-v1.5  prefix=False")
print("-" * 72)
for pos, nid, q in CASES:
    qv = model.encode([q], normalize_embeddings=True)[0]
    sims = embs @ qv
    order = np.argsort(-sims)
    rank = None
    for r, idx in enumerate(order, 1):
        key = docs[idx][0]
        if key[0] == 'node' and key[1] == nid:
            rank = r
            break
    is_hit = rank is not None and rank <= 3
    res[pos][0] += is_hit
    res[pos][1] += 1
    print(f"[{pos}] node={nid:2d} rank={rank} hit3={is_hit} | {q}")

print("-" * 72)
h, ht = res['head']; t, tt = res['tail']
print(f"头部 recall@3 = {h}/{ht} = {h/ht:.1%}")
print(f"尾部 recall@3 = {t}/{tt} = {t/tt:.1%}")
print(f"整体 recall@3 = {h+t}/{ht+tt} = {(h+t)/(ht+tt):.1%}")
