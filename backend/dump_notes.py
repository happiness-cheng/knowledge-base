"""只读：导出指定 node 的完整正文，供人工挑取 gold 片段。"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
targets = [int(a) for a in sys.argv[1:]] or [1, 2, 7, 8, 12, 14, 16, 17, 18]
c = sqlite3.connect(f'file:{Path.home() / ".knowledge_base" / "knowledge.db"}?mode=ro',
                    uri=True)
for nid in targets:
    row = c.execute('SELECT title, content FROM knowledge_nodes WHERE id=?', (nid,)).fetchone()
    if not row:
        print(f'node {nid}: 不存在')
        continue
    title, content = row
    print('#' * 100)
    print(f'# node {nid}  {title!r}   {len(content)} 字符')
    print('#' * 100)
    print(content)
    print()
c.close()
