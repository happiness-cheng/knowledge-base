"""只读：列出全部真实笔记，供人工分类（复制粘贴型 vs 手写口语型）。"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
c = sqlite3.connect(f'file:{Path.home() / ".knowledge_base" / "knowledge.db"}?mode=ro',
                    uri=True)
rows = c.execute(
    'SELECT id, title, category, LENGTH(content), content FROM knowledge_nodes ORDER BY id'
).fetchall()
c.close()

print(f'共 {len(rows)} 条笔记\n')
for nid, title, cat, ln, content in rows:
    print('=' * 120)
    print(f'node {nid}   title={title!r}   category={cat!r}   字符数={ln}')
    # 前 260 字，够判断文风
    preview = content[:260].replace('\n', ' ⏎ ')
    print(f'  预览: {preview}')
