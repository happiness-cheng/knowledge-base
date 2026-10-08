"""Q: 损坏集合 "knowledge_nodes" 的向量数据还在不在（决定"可修复"还是"已丢失"）。

判据：
  embeddings 表的行数和总字节数 —— 每行是一条向量（384 维 float32 = 1536 字节）
  如果行数=38 且字节正常 ⇒ **向量数据在，只是 HNSW 索引文件丢了**，可重建
  如果 0 行 ⇒ 数据已丢，只能从关系库重嵌入
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(f'file:{BASE / "chroma_db" / "chroma.sqlite3"}?mode=ro', uri=True)

print('=== knowledge_nodes 的向量数据 ===')
q = '''
SELECT COUNT(*) AS n,
       SUM(LENGTH(vector)) AS total_bytes,
       MIN(LENGTH(vector)) AS min_bytes,
       MAX(LENGTH(vector)) AS max_bytes
FROM embeddings e
JOIN segments s ON e.segment_id = s.id
JOIN collections c ON s.collection = c.id
WHERE c.name = 'knowledge_nodes' AND e.vector IS NOT NULL
'''
for r in con.execute(q):
    n, total, mn, mx = r
    print(f'  非空向量行数 = {n}')
    print(f'  总字节 = {total}  单条 min={mn} max={mx}')
    if mn:
        print(f'  → 单条 {mn} 字节 = {mn // 4} 维 float32')

print('\n=== 对照组：user_1_nodes（1024 维，应 4096 字节/条）===')
q2 = q.replace("'knowledge_nodes'", "'user_1_nodes'")
for r in con.execute(q2):
    n, total, mn, mx = r
    print(f'  非空向量行数 = {n}  单条 min={mn}（{mn // 4 if mn else 0} 维）')

print('\n=== 元数据（文档/标题）还在吗 ===')
q3 = '''
SELECT COUNT(*) FROM embedding_metadata em
JOIN embeddings e ON em.id = e.id
JOIN segments s ON e.segment_id = s.id
JOIN collections c ON s.collection = c.id
WHERE c.name = 'knowledge_nodes'
'''
for r in con.execute(q3):
    print(f'  embedding_metadata 行数 = {r[0]}')

con.close()
