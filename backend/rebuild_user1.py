"""用最终语料重建 user_1_nodes 实库（bge 1024维）

⚠️⚠️ 危险脚本，已加锁 ⚠️⚠️
  它做的是：`col.get()` → `col.delete(所有)` → 用 **eval/corpus_*.json（评测语料）** 灌回。
  两个致命点：
    1. 灌进去的是**评测数据**，不是真实笔记 → 真实笔记被挤出向量库（生产返回负 id 的根因）
    2. 删完没有可用的回滚源（真值在 MySQL，不在这个 json 里）→ **不可回滚**
  生产集合现在由 `build_prod_collection.py` 从 MySQL 重建，本脚本已退役。
  确需运行请显式设置环境变量：$env:ALLOW_DESTRUCTIVE_REBUILD="1"
"""
import os
import sys

if os.environ.get("ALLOW_DESTRUCTIVE_REBUILD") != "1":
    raise SystemExit(
        "拒绝执行：本脚本会用评测语料覆盖真实笔记的向量集合，且不可回滚。\n"
        "生产集合请改用 build_prod_collection.py（数据源 = MySQL）。\n"
        '确需运行：$env:ALLOW_DESTRUCTIVE_REBUILD="1"'
    )

sys.stdout.reconfigure(encoding='utf-8')
import os
os.environ['HF_HUB_OFFLINE'] = '1'
import json
sys.path.insert(0, '.')
from app.services.rag_service import get_embedding, _get_user_collection

short = json.load(open('eval/corpus_short.json', encoding='utf-8'))
chunks = json.load(open('eval/corpus_chunked.json', encoding='utf-8'))
col = _get_user_collection(1)

ids, embs, docs, metas = [], [], [], []
for d in short:
    if len(d['content'] or '') < 30:
        continue
    ids.append(str(d['node_id']))
    embs.append(get_embedding(f"{d['title']}\n{d['content']}"))
    docs.append(d['content'])
    metas.append({'title': d['title'], 'node_id': d['node_id'], 'source': 'short'})

chunk_id = -1
for c in chunks:
    ids.append(str(chunk_id))
    embs.append(get_embedding(f"{c['chunk_title']}\n{c['content']}"))
    docs.append(c['content'])
    metas.append({'title': c['chunk_title'], 'node_id': chunk_id, 'source': c['source_file']})
    chunk_id -= 1

existing = col.get()
if existing['ids']:
    col.delete(ids=existing['ids'])
col.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
print(f'user_1_nodes 重建完成: {col.count()} 条')
