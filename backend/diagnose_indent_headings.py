"""证实"缩进标题被漏检"假设（只读，不改任何东西）。

假设 H：node5 的小节标题带前导空格，`line.startswith('## ')` 匹配不到，
        导致 8 个小节被合并成 1 个 section，再被按标点硬切成 5 块。
判据：若为真，则"识别到的标题数"=1（只有顶格的 Collector），且 chunk 里会混多个主题。
"""
import re
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.utils.markdown_cleaner import _n_tokens, split_by_headings  # noqa: E402

con = sqlite3.connect(f'file:{Path.home() / ".knowledge_base" / "knowledge.db"}?mode=ro',
                      uri=True)

# 全文扫描：有多少行是"带前导空白的 ## 标题"
print('=== 全库扫描：缩进标题 ===')
total_indented = 0
for nid, title, content in con.execute(
        'SELECT id, title, content FROM knowledge_nodes ORDER BY id'):
    indented = [l for l in content.split('\n')
                if re.match(r'^\s+##\s', l) and not re.match(r'^\s*###', l)]
    top = [l for l in content.split('\n')
           if re.match(r'^##\s', l) and not re.match(r'^###', l)]
    total_indented += len(indented)
    if indented:
        print(f'  node {nid:<3} {title[:22]!r:<26} 顶格## 有 {len(top)} 个，'
              f'**缩进## 有 {len(indented)} 个**')
print(f'  ⇒ 全库共 {total_indented} 个缩进标题会被漏检')

# 逐个看切分结果
print('\n=== 当前 split_by_headings 的实际产出 ===')
for nid in (5, 13, 3):
    title, content = con.execute(
        'SELECT title, content FROM knowledge_nodes WHERE id=?', (nid,)).fetchone()
    chunks = split_by_headings(content)
    print(f'\nnode {nid} {title!r}  {len(content)} 字符 → {len(chunks)} 块')
    for i, (heading, body) in enumerate(chunks):
        # 这个 chunk 里"混"了几个小节标题？
        inner = re.findall(r'^\s*##\s+(.+)$', body, flags=re.M)
        print(f'  [{i}] heading={heading[:26]!r:<28} tokens={_n_tokens(body):>4} '
              f'chars={len(body):>5}  内含小节={inner}')

con.close()
