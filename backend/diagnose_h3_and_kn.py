"""两个只读探查：
  Q1 损坏集合 knowledge_nodes 里那 38 条到底是什么、能否从别处恢复
  Q2 H3（`###`）小节会不会滞留在 chunk 内部（H2 切分的盲区）
"""
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402

CHROMA = BASE / 'chroma_db' / 'chroma.sqlite3'
NOTES = Path.home() / '.knowledge_base' / 'knowledge.db'

# ---------------- Q1 ----------------
print('=' * 72)
print('Q1  损坏集合 knowledge_nodes 的内容构成（只读元数据，不碰 HNSW）')
con = sqlite3.connect(f'file:{CHROMA}?mode=ro', uri=True)
q = '''
SELECT em.key, em.string_value, em.int_value
FROM embedding_metadata em
JOIN embeddings e ON em.id = e.id
JOIN segments s ON e.segment_id = s.id
JOIN collections c ON s.collection = c.id
WHERE c.name = 'knowledge_nodes'
'''
rows = con.execute(q).fetchall()
con.close()

by_id = {}
keys = set()
for key, sv, iv in rows:
    keys.add(key)
print(f'  元数据 key 集合: {sorted(keys)}')

# 统计标题
titles = [sv for k, sv, iv in rows if k == 'title']
print(f'  带 title 的记录数: {len(titles)}')
print(f'  前 12 个 title: {titles[:12]}')

# ---------------- Q2 ----------------
print('\n' + '=' * 72)
print('Q2  H3 小节滞留检测（当前切分器）')
con = sqlite3.connect(f'file:{NOTES}?mode=ro', uri=True)
notes = list(con.execute('SELECT id, title, content FROM knowledge_nodes ORDER BY id'))
con.close()

total_inner_h3 = 0
for nid, title, content in notes:
    chunks = split_by_headings(content)
    inner = []
    for i, (heading, body) in enumerate(chunks):
        h3s = re.findall(r'^\s*###\s+(.+)$', body, flags=re.M)
        h2s = re.findall(r'^\s*##\s+(.+)$', body, flags=re.M)
        if h3s or h2s:
            inner.append((i, heading[:20], h2s, h3s))
            total_inner_h3 += len(h3s)
    if inner:
        print(f'\n  node {nid} {title[:20]!r} —— {len(chunks)} 块，'
              f'其中 {len(inner)} 块内部还嵌着标题:')
        for i, hd, h2s, h3s in inner[:4]:
            print(f'    [{i}] heading={hd!r} 内含 ##={h2s} ###={h3s[:3]}')
print(f'\n  ⇒ 全库 chunk 内部残留的 ### 标题共 {total_inner_h3} 个')

# 一个具体例子：node3 的第 0 块有多大、里面有几个 ###
for nid, title, content in notes:
    if nid == 3:
        chunks = split_by_headings(content)
        hd, body = chunks[0]
        print(f'\n  样例 node3[0] heading={hd!r} tokens={_n_tokens(body)}')
        print(f'    内含 ### 小节: {re.findall(r"^\\s*###\\s+(.+)$", body, flags=re.M)}')
