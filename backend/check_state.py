"""只读：看清各集合的现状（不写入、不删除）

集合名不手写：统一走 rag_service.get_collection_name()——迁移期间手写字符串会出现
"脚本看的集合"和"代码写的集合"不是同一个，且不报错。
"""
import sys
sys.path.insert(0, r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')
from app.services import rag_service

QUERY = "为什么需要堆内存，栈空间默认多大"
USER_ID = 1

TARGETS = [
    ("旧生产集合", rag_service.get_collection_name(USER_ID, "")),
    ("新生产集合", rag_service.get_collection_name(USER_ID, "_prod")),
    ("评测集合", rag_service.get_collection_name(USER_ID, "_eval")),
    ("当前生效（由 KB_CHROMA_SUFFIX 决定）", rag_service.get_collection_name(USER_ID)),
]

for label, name in TARGETS:
    print("=" * 60)
    try:
        col = rag_service.chroma_client.get_collection(name=name)
    except Exception as e:
        print(f"{label}: {name} —— 不存在（{type(e).__name__}）")
        continue
    print(f"{label}: {name}  count = {col.count()}")

    # 看全集构成：正 id / 负 id 各多少
    all_ids = col.get()["ids"]
    neg = [i for i in all_ids if str(i).startswith("-") or ":-" in str(i)]
    print(f"  总 id 数 = {len(all_ids)}；看起来是负 id 的 = {len(neg)}")
    print(f"  前 10 个 id = {all_ids[:10]}")

    # 同一个 query 各自的 top-3
    qv = rag_service.get_query_embedding(QUERY)
    res = col.query(query_embeddings=[qv], n_results=3)
    print(f"  query: {QUERY}")
    for i in range(len(res["ids"][0])):
        m = res["metadatas"][0][i]
        d = res["documents"][0][i]
        print(f"    id={res['ids'][0][i]!r:>12}  node_id={m.get('node_id')}  "
              f"chunk={m.get('chunk_index')}  dist={res['distances'][0][i]:.4f}")
        print(f"      title={m.get('title','')[:30]!r}  正文前40字={d[:40]!r}")