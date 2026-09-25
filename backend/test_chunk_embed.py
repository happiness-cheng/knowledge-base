import sys
sys.path.insert(0, 'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3
from app.services import rag_service

# 取 node3（4095 字符）真实内容
c = sqlite3.connect(r'C:/Users/陈独秀/.knowledge_base/knowledge.db')
content, title = c.execute("SELECT content, title FROM knowledge_nodes WHERE id=3").fetchone()
c.close()

# 写入测试集合 user_999（不碰生产）
rag_service.add_node_to_index(3, content, title, user_id=999)
col = rag_service._get_user_collection(999)
print(f"node3 切块数（user_999 集合）= {col.count()}")

# 检索深尾 query，看去重 + 命中
for q in ["为什么需要堆内存，栈空间默认多大", "左值引用和右值引用分别绑定什么"]:
    rs = rag_service.retrieve_relevant_nodes(q, top_k=3, user_id=999)
    print(f"\nquery: {q}")
    for r in rs:
        print(f"  node={r['node_id']} chunk={r['chunk_index']} heading={r['heading'][:20]} | {r['content'][:40]}")

# 清理测试集合
try:
    col.delete(where={"node_id": 3})
    print("\n[cleaned] 测试集合 user_999 已清空 node3")
except Exception as e:
    print(f"cleanup warn: {e}")
