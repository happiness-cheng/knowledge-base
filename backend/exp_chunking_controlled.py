"""P0-1 控制变量实验：修复"缩进标题被漏检"对检索的效果。

控制变量设计（同一脚本内跑完两种策略，保证除切分策略外全部相同）：
  固定：笔记集合(12条/MySQL-SQLite)、embedding 模型(bge-large-zh-v1.5)、
        是否归一化(是)、query 文本(12条冻结集)、top_k(3)、距离度量(L2²)
  变量：**只有切分策略**
        A = 现状 split_by_headings（`line.startswith('## ')`）
        B = 候选 缩进容忍版（`^\s*##\s`）

为什么能这样比：两种策略都在**内存里重算向量**，不写任何集合，读的都是同一份原文。
这样避开了"改了库就要重建、重建后 gold 漂移"的干扰——这是比"改集合再测"更干净的控制。

指标：
  · node 级 Recall@3 / MRR（gold 是 node_id，不随 chunk 边界漂移，天然控制变量）
  · chunk 总数（切分粒度变化）
  · 每 chunk 平均 token（粒度是否合理）
  · 单条 query 检索延迟（中位数）
"""
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import (  # noqa: E402
    MAX_CONTENT_TOKENS, _n_tokens, _split_long_section, split_by_headings)

SQLITE = Path.home() / '.knowledge_base' / 'knowledge.db'

# ---------------------------------------------------------------- 冻结评测集
# gold 用 node_id（不随 chunk 边界漂移）。每条 query 的答案都人工核对过存在于该 node 正文。
# 分组：FIX = 本缺陷直接影响；CTRL = 对照（不应变差）
CASES = [
    # --- FIX：node5 内部各小节（缩进标题导致被合并）---
    ("F1", 5, "监控服务为什么用无锁计数器而不是互斥锁", "Monitor/atomic 无锁"),
    ("F2", 5, "事件为什么要先在内存里排队再交给下游处理", "Queue 解耦 I/O 与处理"),
    ("F3", 5, "限流脚本怎么保证计数和过期时间是原子执行的", "Rate Limiter/Lua"),
    ("F4", 5, "事件数据攒够一批再落库是哪个模块负责的", "Storage/批量 flush"),
    ("F5", 5, "接收连接以后怎么解决粘包和拆包的问题", "Collector/4字节header"),
    ("F6", 5, "为什么只开两个 I/O 线程而不是八个", "Main/线程数取舍"),
    ("F7", 5, "Redis 挂掉的时候限流和反序列化分别怎么处理", "Processor/Redis fail-open"),
    # --- CTRL：不受本缺陷影响（node3 顶格标题、node13 无标题）---
    ("C1", 3, "堆内存和栈空间在大小和管理方式上有什么不同", "node3/堆内存"),
    ("C2", 3, "把资源所有权从一个对象转给另一个对象是为了解决什么开销", "node3/移动语义"),
    ("C3", 3, "多个线程同时拷贝同一个智能指针会不会出问题", "node3/shared_ptr"),
    ("C4", 13, "一个线程要同时盯着成千上万个连接，靠什么机制只拿到就绪的那几个", "node13/epoll 回调"),
    ("C5", 13, "为什么连接数一多，遍历式的方案就不行了", "node13/O(n) vs O(1)"),
]


# ---------------------------------------------------------------- 两种切分策略
def split_candidate(text: str) -> list[tuple[str, str]]:
    """B：缩进容忍版。唯一改动 = 标题判定允许前导空白。

    与现状的差异：
      A: line.startswith('## ') and not line.startswith('### ')
      B: re.match(r'^\\s*##\\s', line) and not re.match(r'^\\s*###\\s', line)
    """
    sections = []
    current_title = "Untitled"
    current_lines = []
    for line in text.split('\n'):
        m2 = re.match(r'^\s*##\s+(.*)$', line)
        m3 = re.match(r'^\s*###\s', line)
        if m2 and not m3:
            if current_lines:
                sections.append((current_title, '\n'.join(current_lines).strip()))
            current_title = m2.group(1).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        content = '\n'.join(current_lines).strip()
        if content:
            sections.append((current_title, content))
    if not sections:
        first_line = text.split('\n')[0].strip() if text.strip() else "Untitled"
        title = first_line.lstrip('#').strip() if first_line.startswith('#') else first_line[:100]
        sections = [(title, text)]

    bounded = []
    for title, content in sections:
        for i, chunk in enumerate(_split_long_section(content)):
            sub = f"{title}({i+1})" if i > 0 else title
            bounded.append((sub, chunk))
    return bounded


# ---------------------------------------------------------------- 数据准备
con = sqlite3.connect(f'file:{SQLITE}?mode=ro', uri=True)
notes = {r[0]: (r[1] or '', r[2] or '') for r in
         con.execute('SELECT id, title, content FROM knowledge_nodes')}
con.close()

model = rag_service._get_model()


def build_pool(splitter):
    """返回 (ids, texts, embeddings, metas) —— 全部在内存里算，不写库"""
    ids, texts, metas = [], [], []
    for nid, (title, content) in notes.items():
        for i, (heading, body) in enumerate(splitter(content)):
            embed_text = f"{title}\n{heading}\n{body}" if title else f"{heading}\n{body}"
            ids.append(f"{nid}:{i}")
            texts.append(embed_text)
            metas.append({'node_id': nid, 'chunk_index': i, 'heading': heading,
                          'tokens': _n_tokens(body), 'body': body})
    t0 = time.perf_counter()
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    build_ms = (time.perf_counter() - t0) * 1000
    return ids, embs, metas, build_ms


def evaluate(ids, embs, metas, label):
    rows = []
    lat = []
    for cid, gold, query, note in CASES:
        t0 = time.perf_counter()
        qv = np.asarray(
            rag_service.get_embedding(rag_service.QUERY_PREFIX + query), dtype=np.float32)
        d = np.linalg.norm(embs - qv[None, :], axis=1)
        order = np.argsort(d)
        lat.append((time.perf_counter() - t0) * 1000)
        # 按 node 去重，取每个 node 的最佳排名（与生产 retrieve_relevant_nodes 语义一致）
        seen, ranked = set(), []
        for idx in order:
            nid = metas[idx]['node_id']
            if nid in seen:
                continue
            seen.add(nid)
            ranked.append((nid, idx))
            if len(ranked) >= 3:
                break
        rank = next((r for r, (nid, _) in enumerate(ranked, 1) if nid == gold), None)
        hit3 = rank is not None and rank <= 3
        rows.append((cid, gold, rank, hit3, ranked[0][0] if ranked else None,
                     metas[ranked[0][1]]['heading'][:22] if ranked else '',
                     note))
    n = len(rows)
    r3 = sum(1 for r in rows if r[3]) / n
    mrr = sum(1 / r[2] for r in rows if r[2]) / n
    return rows, r3, mrr, statistics.median(lat)


strategies = {
    'A 现状（漏检缩进标题）': split_by_headings,
    'B 候选（缩进容忍）': split_candidate,
}

results = {}
print('=' * 78)
for label, sp in strategies.items():
    ids, embs, metas, build_ms = build_pool(sp)
    rows, r3, mrr, lat = evaluate(ids, embs, metas, label)
    avg_tok = statistics.mean(m['tokens'] for m in metas)
    results[label] = (rows, r3, mrr, lat, len(metas), avg_tok, build_ms)
    print(f'{label}')
    print(f'  chunk 总数={len(metas)}  平均 {avg_tok:.0f} token  '
          f'（预算 {MAX_CONTENT_TOKENS}）  全量编码 {build_ms:.0f}ms')
    print(f'  Recall@3 = {r3:.3f}   MRR = {mrr:.3f}   单query检索中位延迟 = {lat:.1f}ms')

print('\n' + '=' * 78)
print('逐条对比（rank=该 gold node 在去重后的名次，None=未进前3）')
print(f'{"id":<4}{"gold":<6}{"A rank":<8}{"B rank":<8}{"变化":<8} 说明')
la, lb = list(results.values())[0], list(results.values())[1]
for ra, rb in zip(la[0], lb[0]):
    a, b = ra[2], rb[2]
    mark = ''
    if a is None and b is not None:
        mark = '✅ 救回'
    elif a is not None and b is None:
        mark = '❌ 退化'
    elif a != b:
        mark = ('↑' if (b or 99) < (a or 99) else '↓')
    print(f'{ra[0]:<4}{ra[1]:<6}{str(a):<8}{str(b):<8}{mark:<8} {ra[6]}')

print('\n' + '=' * 78)
print('分组统计')
for grp, name in (('F', 'FIX 组（node5）'), ('C', 'CTRL 组（node3/13）')):
    for label, (rows, r3, mrr, lat, nc, at, bm) in results.items():
        sub = [r for r in rows if r[0].startswith(grp)]
        sr3 = sum(1 for r in sub if r[3]) / len(sub)
        smrr = sum(1 / r[2] for r in sub if r[2]) / len(sub)
        print(f'  {name:<20} {label:<22} Recall@3={sr3:.3f}  MRR={smrr:.3f}')
