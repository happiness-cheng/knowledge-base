"""量清"时间信号"从哪里来：标题里的日期 vs DB 的 created_at。

动机：为"数据新鲜度"提供时间元数据。两个候选来源：
  A 标题里的日期（如 `# 交易日志 - 2026-05-20`）—— 是**被记录事件**的日期
  B DB 的 `created_at` —— 是**该条笔记被创建/导入**的时间
两者可能差几个月（5 月的交易日志可能 9 月才整理进来）。
若差异大，用 B 做"数据新鲜度"会误导；应优先用 A，B 作补充。
"""
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')

con = sqlite3.connect(f'file:{Path.home() / ".knowledge_base" / "knowledge.db"}?mode=ro',
                      uri=True)
rows = con.execute(
    'SELECT id, title, content, created_at, updated_at FROM knowledge_nodes ORDER BY id'
).fetchall()
con.close()

DATE_PAT = re.compile(r'(20\d{2})[-/年.](\d{1,2})[-/月.](\d{1,2})')

print(f'{"id":<5}{"标题":<30}{"标题里的日期":<16}{"created_at":<22}{"差(天)":<9}正文首行日期')
print('-' * 108)
for nid, title, content, created, updated in rows:
    head = (content or '').split('\n')[0][:40]
    m = DATE_PAT.search(f'{title}\n{head}')
    note_date = f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else '-'
    ca = (created or '')[:19]
    diff = ''
    if m and created:
        try:
            d1 = datetime.strptime(note_date, '%Y-%m-%d')
            d2 = datetime.strptime(str(created)[:10], '%Y-%m-%d')
            diff = str(abs((d1 - d2).days))
        except Exception:
            diff = '?'
    print(f'{nid:<5}{(title or "")[:28]:<30}{note_date:<16}{ca:<22}{diff:<9}{head[:30]}')

print('\n结论判读：')
print('  · 标题/正文里有明确日期的笔记 → 用那个日期作为 note_date')
print('  · 没有日期的 → 退回 created_at（并标明这是"入库时间"而非"事件时间"）')
