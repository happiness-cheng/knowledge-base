"""诊断 collection "knowledge_nodes" 的真实身份与损坏范围（只读）。

三个问题：
  Q1 它是什么时候建的、装的是什么      → 读 chroma.sqlite3 的 collections 表
  Q2 是"只有 HNSW 索引坏"还是"数据也没了" → 对比 collection 目录里的文件大小
  Q3 生产代码还会不会碰它               → 由 grep 另行确认
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
CHROMA = BASE / 'chroma_db'
sys.stdout.reconfigure(encoding='utf-8')

# --- Q1: 元数据（sqlite 是只读打开，加 mode=ro 防止意外写入） ---
con = sqlite3.connect(f'file:{CHROMA / "chroma.sqlite3"}?mode=ro', uri=True)
con.row_factory = sqlite3.Row

print('=== collections 表 ===')
for r in con.execute('SELECT * FROM collections'):
    print(dict(r))

print('\n=== segments（集合 → 段 UUID）===')
try:
    for r in con.execute('SELECT * FROM segments'):
        d = dict(r)
        print({k: d[k] for k in d if k in ('id', 'collection', 'type', 'scope')})
except Exception as e:
    print(f'  读取失败: {e}')

print('\n=== 各集合的 embedding 条数（只看元数据，不碰 HNSW）===')
try:
    rows = con.execute('''
        SELECT c.name, COUNT(e.id) AS n
        FROM collections c
        LEFT JOIN segments s ON s.collection = c.id
        LEFT JOIN embeddings e ON e.segment_id = s.id
        GROUP BY c.name ORDER BY n DESC
    ''').fetchall()
    for r in rows:
        print(f'  {r["name"]:<24} {r["n"]} 条')
except Exception as e:
    print(f'  读取失败: {e}')

con.close()

# --- Q2: 目录层面看损坏范围 ---
print('\n=== 每个集合目录的文件（HNSW 索引 = *.bin）===')
seg_dirs = [d for d in CHROMA.iterdir() if d.is_dir() and len(d.name) == 36]
for d in sorted(seg_dirs):
    files = sorted(d.rglob('*'))
    total = sum(f.stat().st_size for f in files if f.is_file())
    bins = [f for f in files if f.suffix == '.bin']
    bin_info = ', '.join(f'{f.name}={f.stat().st_size}' for f in bins) or '无 .bin'
    print(f'  {d.name}  共{total:>9} 字节  {bin_info}')
