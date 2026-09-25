"""T1 after 测量：12 条笔记切分后重嵌入，测整体 recall，对比 before。
匹配规则：笔记的任一块（chunk）命中 top-3 就算命中（父子切割的 recall 口径）。
"""
import json
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import numpy as np

os.environ['HF_HUB_OFFLINE'] = '1'
from sentence_transformers import SentenceTransformer
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
from app.utils.markdown_cleaner import split_by_headings

# 12 短笔记（全文） + 287 外部 chunks
short = {d['node_id']: d for d in json.load(open('corpus_short.json', encoding='utf-8'))}
chunked = json.load(open('corpus_chunked.json', encoding='utf-8'))

# 构建 doc 列表：切分后的笔记 chunk（带 parent_node_id）+ 外部 chunks（不变）
docs = []
for nid, d in short.items():
    sections = split_by_headings(d['content'])
    for i, (sect_title, sect_content) in enumerate(sections):
        embed_text = f"{d['title']}\n{sect_title}\n{sect_content}"
        docs.append((('note', nid, i), embed_text))
for c in chunked:
    docs.append((('ext', c['source_file'], c['chunk_index']), f"{c['chunk_title']}\n{c['content']}"))

model = SentenceTransformer('BAAI/bge-large-zh-v1.5')
texts = [t for _, t in docs]
embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

QUERY_PREFIX = "为这个句子生成表示以用于检索相关文章："

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
print(f"docs={len(docs)}（笔记切分后 {len(docs)-len(chunked)} 块 + 外部 {len(chunked)} 块）")
print("-" * 72)
for pos, nid, q in CASES:
    qv = model.encode([QUERY_PREFIX + q], normalize_embeddings=True)[0]
    sims = embs @ qv
    order = np.argsort(-sims)
    rank = None
    for r, idx in enumerate(order, 1):
        key = docs[idx][0]
        if key[0] == 'note' and key[1] == nid:
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
