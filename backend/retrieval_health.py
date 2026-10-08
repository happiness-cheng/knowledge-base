"""生产检索健康检查：走**真实读路径**（ChromaDB + HNSW + 生产集合），测真实笔记。

与 eval/baseline_v2.py 的分工（两者测的不是一回事，别混）：
  baseline_v2.py   测"评测语料池"（299 条，内存暴力余弦）→ 衡量**检索算法**
  retrieval_health.py 测"生产集合"（真实笔记 57 块，走 rag_service.retrieve_relevant_nodes
                   → ChromaDB HNSW）→ 衡量**线上实际行为**

评价口径（直接对齐生产语义，不需要模拟）：
  · 调 rag_service.retrieve_relevant_nodes(query, top_k=3)
  · gold 是 **node 级**（不随 chunk 边界漂移）——这是能跨切分策略比较的前提
  · 指标：Recall@3（gold node 是否进前 3）、MRR（gold node 的排名倒数）
  · 同时记录命中块与 heading，用于人工判断"是不是答到点上"

评测集：从既有痕迹抽取（tracker 记录过的深尾 query、eval CASES 中指向真实笔记的条目、
P0-1 实验的 FIX/CTRL 组），全部人工核对过答案存在于该 node 正文。冻结不随优化变动。
"""
import json
import sys
import time
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402

# (id, gold_node_id, query, 答案在原文中的定位说明)
CASES = [
    ("F1", 5, "监控服务为什么用无锁计数器而不是互斥锁", "Monitor: 只读 11 个 atomic 计数器，无锁读"),
    ("F2", 5, "事件为什么要先在内存里排队再交给下游处理", "Queue: 解耦 I/O 线程和处理线程"),
    ("F3", 5, "限流脚本怎么保证计数和过期时间是原子执行的", "Rate Limiter: Lua 脚本原子执行 INCR+EXPIRE"),
    ("F4", 5, "事件数据攒够一批再落库是哪个模块负责的", "Storage: 内部维护 buffer 批量 flush"),
    ("F5", 5, "接收连接以后怎么解决粘包和拆包的问题", "Collector: 先读 4 字节 header"),
    ("F6", 5, "为什么只开两个 I/O 线程而不是八个", "Main: 瓶颈在网络 I/O 不在 CPU"),
    ("F7", 5, "Redis 挂掉的时候限流和反序列化分别怎么处理", "Processor: Redis 挂了走 fail-open"),
    ("F8", 5, "监控数据是怎么被外部系统定期拉走的", "Monitor: Prometheus 每 15 秒爬取 :9090"),
    ("D1", 3, "为什么需要堆内存，栈空间默认多大", "node3 尾部: 栈 Linux 默认 8MB"),
    ("D2", 3, "堆内存和栈空间在大小和管理方式上有什么不同", "node3: 堆可运行时任意分配"),
    ("D3", 3, "把资源所有权从一个对象转给另一个对象是为了解决什么开销", "node3: 移动语义避免昂贵拷贝"),
    ("D4", 3, "多个线程同时拷贝同一个智能指针会不会出问题", "node3: 引用计数原子，对象本身不安全"),
    ("D5", 3, "多个线程同时改同一个智能指针的指向安全吗", "node3: 不安全，需额外同步"),
    ("D6", 13, "一个线程要同时盯着成千上万个连接，靠什么机制只拿到就绪的那几个", "node13: epoll 回调机制"),
    ("D7", 13, "为什么连接数一多，遍历式的方案就不行了", "node13: select/poll 每次传全部 fd"),
    ("D8", 12, "建立可靠连接的时候为什么握手要来三个回合", "node12: 三次握手"),
    ("D9", 7, "网站地址栏变成 https 之后数据在传输时做了哪些额外的安全处理", "node7: HTTPS"),
    ("D10", 17, "编译期常量和预处理宏定义一个数值用哪个更好", "node17: const VS define"),
]


def main():
    col = rag_service._get_user_collection(1)
    print('=' * 78)
    print(f'生产检索健康检查  集合={col.name}  count={col.count()}  '
          f'后缀={rag_service._SUFFIX!r}')

    # 预热：首次调用会加载 bge 模型（实测单次 ~11.6s），不预热会把冷启动算进延迟里
    t_warm = time.perf_counter()
    rag_service.retrieve_relevant_nodes('预热', top_k=1, user_id=1)
    print(f'  [预热] 模型加载 + 首次检索 {(time.perf_counter() - t_warm) * 1000:.0f}ms '
          f'（不计入下方延迟统计）')

    hits, mrr, lat = 0, 0.0, []
    fails = []
    for cid, gold, query, note in CASES:
        t0 = time.perf_counter()
        res = rag_service.retrieve_relevant_nodes(query, top_k=3, user_id=1)
        lat.append((time.perf_counter() - t0) * 1000)
        rank = next((i for i, r in enumerate(res, 1) if r['node_id'] == gold), None)
        if rank:
            hits += 1
            mrr += 1.0 / rank
        else:
            fails.append((cid, gold, query, note, res))
        top = res[0] if res else None
        flag = '✅' if rank == 1 else ('○' if rank else '❌')
        print(f"  {flag} {cid:<4} gold={gold:<3} rank={str(rank):<5} "
              f"top1=node{top['node_id'] if top else '-'}:{top.get('chunk_index') if top else '-'}"
              f"({(top.get('heading') or '')[:20] if top else ''})  cos≈"
              f"{(1 - (top['distance'] ** 2) / 2):.3f}" if top else '')

    n = len(CASES)
    print('-' * 78)
    print(f'  Recall@3 = {hits}/{n} = {hits / n:.3f}')
    print(f'  MRR      = {mrr / n:.3f}')
    print(f'  检索延迟  = 中位 {sorted(lat)[len(lat) // 2]:.1f}ms  '
          f'最大 {max(lat):.1f}ms')
    if fails:
        print('\n  未进前 3（含人工判断所需信息）:')
        for cid, gold, query, note, res in fails:
            print(f'    {cid} 期望 node{gold} —— {note}')
            for i, r in enumerate(res, 1):
                print(f'       #{i} node={r["node_id"]} chunk={r.get("chunk_index")} '
                      f'heading={r.get("heading", "")[:26]!r}')

    out = BASE / 'eval' / 'retrieval_health_baseline.json'
    out.write_text(json.dumps({
        'measured_at': '2026-10-07',
        'collection': col.name, 'count': col.count(),
        'suffix': rag_service._SUFFIX,
        'n_cases': n, 'recall@3': hits / n, 'mrr': mrr / n,
        'median_latency_ms': sorted(lat)[len(lat) // 2],
        'cases': [{'id': c, 'gold': g, 'query': q, 'note': nt} for c, g, q, nt in CASES],
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n  已写: {out.name}')


if __name__ == '__main__':
    main()
