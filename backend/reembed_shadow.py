"""真实 re-embed：12 条笔记切分后写入影子集合 user_1_nodes_v2（不碰生产 user_1_nodes）。
父子切割 + query 前缀，验证深尾 query 命中。
"""
import sys
import sqlite3
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
from app.services import rag_service
from app.utils.markdown_cleaner import split_by_headings

# 影子集合
shadow = rag_service.chroma_client.get_or_create_collection(name="user_1_nodes_v2")

# 读 12 笔记（从旧 SQLite；生产 MySQL 未起，笔记内容一致）
c = sqlite3.connect(r'C:/Users/陈独秀/.knowledge_base/knowledge.db')
rows = c.execute("SELECT id, title, content FROM knowledge_nodes ORDER BY id").fetchall()
c.close()

total_chunks = 0
for nid, title, content in rows:
    chunks = split_by_headings(content)
    ids, embeddings, documents, metadatas = [], [], [], []
    for i, (heading, cc) in enumerate(chunks):
        ids.append(f"{nid}:{i}")
        embeddings.append(rag_service.get_embedding(f"{title}\n{heading}\n{cc}" if title else f"{heading}\n{cc}"))
        documents.append(cc)
        metadatas.append({"title": title, "node_id": nid, "chunk_index": i, "heading": heading})
    shadow.upsert(ids=ids, embeddings=embeddings, documents=documents, metadatas=metadatas)
    total_chunks += len(chunks)

print(f"影子集合 user_1_nodes_v2：{len(rows)} 条笔记 → {total_chunks} 块")

# 验证：深尾 query 命中（带前缀）
for q in ["为什么需要堆内存，栈空间默认多大", "监控服务为什么用无锁计数器而不是互斥锁"]:
    qv = rag_service.get_query_embedding(q)
    res = shadow.query(query_embeddings=[qv], n_results=3)
    hits = [(r['metadatas'][0]['node_id'], r['metadatas'][0]['chunk_index'], r['documents'][0][:30]) for r in [res] if r['ids']]
    # 上面写法啰嗦，重写：
    print(f"\nquery: {q}")
    if res and res['ids'] and res['ids'][0]:
        for i in range(len(res['ids'][0])):
            m = res['metadatas'][0][i]
            print(f"  node={m['node_id']} chunk={m['chunk_index']} heading={m['heading'][:16]} | {res['documents'][0][i][:32]}")
