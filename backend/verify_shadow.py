import sys
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
from app.services import rag_service

shadow = rag_service.chroma_client.get_collection(name="user_1_nodes_v2")
print(f"影子集合 user_1_nodes_v2 count = {shadow.count()}")

for q in ["为什么需要堆内存，栈空间默认多大", "监控服务为什么用无锁计数器而不是互斥锁"]:
    qv = rag_service.get_query_embedding(q)
    res = shadow.query(query_embeddings=[qv], n_results=3)
    print(f"\nquery: {q}")
    if res and res['ids'] and res['ids'][0]:
        for i in range(len(res['ids'][0])):
            m = res['metadatas'][0][i]
            d = res['documents'][0][i]
            print(f"  node={m['node_id']} chunk={m['chunk_index']} heading={m.get('heading','')[:18]} | {d[:42]}")
