"""查 chroma.sqlite3 的表结构（别再猜列名）。"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
con = sqlite3.connect(f'file:{BASE / "chroma_db" / "chroma.sqlite3"}?mode=ro', uri=True)

print('=== 表清单 ===')
tables = [r[0] for r in con.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(' ', tables)

for t in ('embeddings', 'embedding_metadata', 'embedding_fulltext_search'):
    if t not in tables:
        continue
    print(f'\n=== {t} 的列 ===')
    for r in con.execute(f'PRAGMA table_info({t})'):
        print(f'  {r[1]:<20} {r[2]}')

print('\n=== knowledge_nodes 向量字节（按 embeddings 实际列名）===')
cols = [r[1] for r in con.execute('PRAGMA table_info(embeddings)')]
blob_col = None
for cand in ('vector', 'embedding', 'vec'):
    if cand in cols:
        blob_col = cand
        break
print(f'  候选列: {cols}  → 选用: {blob_col}')

if blob_col:
    q = f'''
    SELECT COUNT(*), SUM(LENGTH(e.{blob_col})), MIN(LENGTH(e.{blob_col})), MAX(LENGTH(e.{blob_col}))
    FROM embeddings e
    JOIN segments s ON e.segment_id = s.id
    JOIN collections c ON s.collection = c.id
    WHERE c.name = ?
    '''
    for name in ('knowledge_nodes', 'user_1_nodes', 'user_1_nodes_v2'):
        for r in con.execute(q, (name,)):
            n, total, mn, mx = r
            dim = (mn // 4) if mn else 0
            print(f'  {name:<20} 向量数={n}  单条={mn}字节({dim}维)  总={total}字节')

con.close()
