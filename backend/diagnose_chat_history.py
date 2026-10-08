"""探查：项目里有没有真实用户提问的历史（这才是构建 query 集的无偏来源）。

若存在 chat messages，按用户真实原话构建 query 集，能避免"自造 query 偏向文档用词"
的系统性偏差——这正是 v1 baseline 偏乐观的根因。
"""
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
db = Path.home() / '.knowledge_base' / 'knowledge.db'
c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)

tables = [r[0] for r in c.execute(
    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
print(f'表: {tables}\n')

for t in ('messages', 'conversations'):
    if t not in tables:
        print(f'{t}: 不存在')
        continue
    n = c.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'=== {t}: {n} 行 ===')
    cols = [r[1] for r in c.execute(f'PRAGMA table_info({t})')]
    print(f'  列: {cols}')

if 'messages' in tables:
    print('\n=== 按角色分布 ===')
    for role, n in c.execute('SELECT role, COUNT(*) FROM messages GROUP BY role'):
        print(f'  {role}: {n}')

    print('\n=== user 消息样本（前 40 条，真实提问）===')
    rows = c.execute(
        "SELECT id, conversation_id, content FROM messages WHERE role='user' "
        "ORDER BY id LIMIT 40").fetchall()
    for i, cid, content in rows:
        flat = (content or '').replace('\n', ' ')[:110]
        print(f'  [{i:>4}] conv={cid:<4} {flat}')

    print('\n=== 消息长度分布（判断是否多为短问句）===')
    for lo, hi in ((0, 10), (10, 20), (20, 40), (40, 80), (80, 200), (200, 10**9)):
        n = c.execute(
            'SELECT COUNT(*) FROM messages WHERE role=\'user\' AND LENGTH(content)>=? '
            'AND LENGTH(content)<?', (lo, hi)).fetchone()[0]
        print(f'  {lo:>3}~{hi if hi < 10**9 else "∞":<5} 字: {n}')

c.close()
