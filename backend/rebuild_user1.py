"""用最终语料重建 user_1_nodes 实库（bge 1024维）"""
import sys
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
