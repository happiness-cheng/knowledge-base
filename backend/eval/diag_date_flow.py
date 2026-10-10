"""验证：检索结果是否带上了笔记日期 + 库内最新日期（生产读路径）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r'C:/Users/陈独秀/knowledge-base/backend')))
import eval._bootstrap  # noqa: F401  必须先导入：设 DATABASE_URL / 净化 NO_PROXY

sys.stdout.reconfigure(encoding='utf-8')

from app.database import SessionLocal  # noqa: E402
from app.services import rag_service  # noqa: E402

print('数据库 =', SessionLocal().get_bind().url.render_as_string(hide_password=True))
print('集合   =', rag_service._get_user_collection(1).name)

for q in ('今天上证指数收盘多少', '为什么要三次握手', 'BFS 一般用什么数据结构'):
    res = rag_service.retrieve_relevant_nodes(q, top_k=3, user_id=1)
    print(f'\nquery: {q}')
    for r in res:
        print(f"  node={r['node_id']:<3} chunk={r.get('chunk_index')} "
              f"note_date={r.get('note_date')!r} source={r.get('date_source')!r} "
              f"kb_latest={r.get('kb_latest_date')!r} "
              f"cos≈{(1 - r['distance'] ** 2 / 2):.3f}  {(r.get('heading') or '')[:20]!r}")
