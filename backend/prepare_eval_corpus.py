"""knowledge-base RAG 评测集 v1 语料准备
1) 从 SQLite 读 12 条本地短笔记 → 存 JSON
2) 长文档(3篇项目md) + 外部语料(6篇CS知识) 切片 → 存 JSON
评测集查询在本脚本产出 corpus 后单独写（需人工读文档）
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import os
import sqlite3

sys.path.insert(0, '.')
# 强制 SQLite（.env 配了 MySQL，本地没起 MySQL 服务）
os.environ['DATABASE_URL'] = 'sqlite:///C:/Users/陈独秀/.knowledge_base/knowledge.db'

SHORT_DOCS = []   # {node_id, title, content}
conn = sqlite3.connect(r'C:/Users/陈独秀/.knowledge_base/knowledge.db')
cur = conn.cursor()
cur.execute('SELECT id, title, content FROM knowledge_nodes ORDER BY id')
for nid, title, content in cur.fetchall():
    SHORT_DOCS.append({"node_id": nid, "title": (title or '').strip(), "content": content or ''})
conn.close()
print(f'本地短笔记: {len(SHORT_DOCS)} 条')

# 长文档+外部语料：用项目自己的 split_by_headings 切片（含刚加的 size 兜底）
from app.utils.markdown_cleaner import split_by_headings

CORPUS_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eval', 'corpus')

CHUNKED = []  # {source_file, chunk_title, chunk_index, content}
for sub in ['long', 'external']:
    corpus_dir = os.path.join(CORPUS_ROOT, sub)
    for fname in os.listdir(corpus_dir):
        if not fname.endswith('.md'):
            continue
        text = open(os.path.join(corpus_dir, fname), encoding='utf-8').read()
        sections = split_by_headings(text)
        for i, (title, content) in enumerate(sections):
            if len(content) < 50:
                continue  # 空壳小节跳过
            CHUNKED.append({
                "source_file": fname,
                "chunk_title": title,
                "chunk_index": i,
                "content": content,
            })
print(f'长文档+外部语料切片: {len(CHUNKED)} chunks（来自 {len(set(c["source_file"] for c in CHUNKED))} 篇）')

os.makedirs('eval', exist_ok=True)
with open('eval/corpus_short.json', 'w', encoding='utf-8') as f:
    json.dump(SHORT_DOCS, f, ensure_ascii=False, indent=2)
with open('eval/corpus_chunked.json', 'w', encoding='utf-8') as f:
    json.dump(CHUNKED, f, ensure_ascii=False, indent=2)
print('已保存: eval/corpus_short.json, eval/corpus_chunked.json')
