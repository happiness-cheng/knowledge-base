"""把评测语料放进独立集合（评测与生产分家）。

背景：09-26 实测生产集合 user_1_nodes 里混了 287 条评测块，用的是**负数 node_id**
（`rebuild_user1.py:23-29`）。负 id 在关系库里查不到 → `get_node_details` 对 287/299 条
结构性失效（`agent_tools.py:152-156`）。根因不是"没给来源标注"，而是**评测数据住进了
生产集合**。

本脚本做三件事（只写评测集合，不碰生产集合）：
1. 从 eval/corpus_short.json + eval/corpus_chunked.json 读评测语料
2. 写入独立集合 user_{uid}_nodes_eval（后缀走 _SUFFIX 的兄弟参数，显式传 "_eval"）
3. **id 用可读字符串而不是负数**：short 用 "short:{node_id}"，
   chunked 用 "eval:{source_file}:{chunk_index}"
   —— id 本身携带来源，检索到就能一眼看出是评测语料，且不会与真实 node_id 混淆。

为什么不用负数：负数是为了"和真实 id 不冲突"，代价是**丢了可读性且让下游查询必然失败**。
用带前缀的字符串同样零冲突，且自解释。
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402

USER_ID = 1
EVAL_SUFFIX = "_eval"

short = json.loads((BASE / 'eval/corpus_short.json').read_text(encoding='utf-8'))
chunked = json.loads((BASE / 'eval/corpus_chunked.json').read_text(encoding='utf-8'))

col = rag_service.chroma_client.get_or_create_collection(
    name=rag_service.get_collection_name(USER_ID, EVAL_SUFFIX)
)

ids, embs, docs, metas = [], [], [], []

for d in short:
    if len(d['content'] or '') < 30:
        continue
    ids.append(f"short:{d['node_id']}")
    embs.append(rag_service.get_embedding(f"{d['title']}\n{d['content']}"))
    docs.append(d['content'])
    metas.append({'title': d['title'], 'source': 'short', 'eval': True})

by_source = {}
for c in chunked:
    by_source.setdefault(c['source_file'], []).append(c)

for src, chunks in by_source.items():
    for i, c in enumerate(chunks):
        ids.append(f"eval:{src}:{i}")
        embs.append(rag_service.get_embedding(f"{c['chunk_title']}\n{c['content']}"))
        docs.append(c['content'])
        metas.append({'title': c['chunk_title'], 'source': src, 'eval': True,
                      'source_file': src, 'chunk_index': i})

# 幂等：先清空本集合再写，避免重复运行叠加
existing = col.get()
if existing['ids']:
    col.delete(ids=existing['ids'])
col.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)

print(f'[评测集合] {col.name}')
print(f'  写入 {len(ids)} 条（short {sum(1 for m in metas if m["source"]=="short")} '
      f'+ chunked {sum(1 for m in metas if m["source"]!="short")}）')
print(f'  count = {col.count()}')
print(f'  id 样例 = {col.get()["ids"][:3]}')
