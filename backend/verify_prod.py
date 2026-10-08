"""验证脚本（K3）：**走生产读路径**看检索结果，不自己算余弦。

为什么不能用 eval/run_kb_eval.py 代替：
  评测脚本自己实现了暴力余弦（`run_kb_eval.py:130-138`），是"精确搜索"，
  完全不经过 ChromaDB 的 ANN 索引 ⇒ 它测不出"生产集合里装了什么"。
  本脚本调用 `rag_service.retrieve_relevant_nodes()`，就是后端线上走的那条路。

健康判据（三条，都有数字）：
  1. 生效集合名 —— 必须与预期一致（`KB_CHROMA_SUFFIX` 决定）
  2. id 极性 —— 正 id 能从关系库查到、能闭环；负 id 结构性失效
  3. 同一 query 的 top-1 是否命中预期的 node/chunk

用法：
  python verify_prod.py            # 看当前生效集合的现状
  PROD=1 python verify_prod.py     # 与上面相同（保留参数位，无需区分）
"""
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402

USER_ID = 1
# 三个探针 query：(说明, query, 预期 node_id)
PROBES = [
    ("深尾·堆内存/栈大小", "为什么需要堆内存，栈空间默认多大", 3),
    ("深尾·无锁计数器", "监控服务为什么用无锁计数器而不是互斥锁", 5),
    ("常见·三次握手", "建立可靠连接的时候为什么握手要来三个回合", 12),
]


def cosine_from_l2(distance: float) -> float:
    """ChromaDB 默认 L2² 距离 → 余弦（归一化向量下 L2² = 2 - 2cos）。

    换算的必要性：评测脚本 `run_kb_eval.py:137` 用的是余弦（越大越近），
    生产 ChromaDB 默认返回 L2²（越小越近）。**两把尺子不能直接比**，
    所以这里统一换算成余弦，才能和 tracker/README 里的 0.478/0.679 等数字对比。
    """
    return 1.0 - (distance ** 2) / 2.0


def main() -> None:
    col = rag_service._get_user_collection(USER_ID)
    name = col.name
    count = col.count()
    all_ids = col.get()['ids']
    neg = [i for i in all_ids if str(i).lstrip('-').isdigit() and str(i).startswith('-')]
    chunked = [i for i in all_ids if ':' in str(i) and not str(i).startswith('-')]

    print('=' * 68)
    print(f'生效集合: {name}')
    print(f'  KB_CHROMA_SUFFIX = {rag_service._SUFFIX!r}')
    print(f'  count        = {count}')
    print(f'  负 id 条数    = {len(neg)}   ← 健康值应为 0')
    print(f'  父子切割块数  = {len(chunked)}  ← 形如 "3:11"')
    print(f'  id 样例      = {all_ids[:6]}')

    print('-' * 68)
    for label, query, expect_node in PROBES:
        results = rag_service.retrieve_relevant_nodes(query, top_k=3, user_id=USER_ID)
        print(f'\n[{label}] {query}')
        print(f'  期望 node_id = {expect_node}')
        if not results:
            print('  ⚠ 返回 0 条 —— 集合为空或取错（非 ANN 参数问题）')
            continue
        for rank, r in enumerate(results, 1):
            d = r.get('distance')
            cos = cosine_from_l2(d) if isinstance(d, (int, float)) else None
            mark = '✅' if (rank == 1 and r['node_id'] == expect_node) else '  '
            print(f'  {mark} #{rank} node={r["node_id"]:<4} chunk={r.get("chunk_index")} '
                  f'L2²={d:.4f} cos≈{cos:.3f}  title={r.get("title", "")[:22]!r}')
            print(f'         heading={r.get("heading", "")[:26]!r} '
                  f'| {r.get("content", "")[:34]!r}')

    print('=' * 68)
    hit1 = all(
        rag_service.retrieve_relevant_nodes(q, top_k=1, user_id=USER_ID)
        and rag_service.retrieve_relevant_nodes(q, top_k=1, user_id=USER_ID)[0]['node_id'] == n
        for _, q, n in PROBES
    )
    print(f'K3 判据 · top-1 全部命中预期 node：{"是 ✅" if hit1 else "否 ❌"}')


if __name__ == '__main__':
    main()
