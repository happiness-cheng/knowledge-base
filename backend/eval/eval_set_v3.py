"""知识库评测集 v3（2026-10-07 重建）——按"笔记类型"分层的检索+拒答评测。

## 为什么重建（v1/v2 的三处方法缺陷）
1. **query 由我自造 → 用词偏向文档**。实测证据：3 条 rank=2 的失败全是同一类
   ——用户说"无锁计数器"，原文写 atomic 计数器。自造 query 系统性偏乐观。
2. **没有分层**。不同类型的笔记失败模式不同：
   · A 复制/LLM 总结型：格式规整（`- **定义/特点/场景/风险**`），提问用词 ≈ 文档用词
     → dense 检索天然占优
   · B 手写/对话辅导型：口语化、含个人语境（如 static 笔记里"你说'全局可以修改'——反了"）
     → 用户提问用词 ≠ 文档用词，**才是 dense 的固有盲区**
   混在一起报一个平均分，等于把两类不同的病平均掉。
3. **没有负例**。用户会问库里没有的东西，必须测拒答/降级，否则线上会把 web_search
   或模型自身知识当成笔记内容答出来（这正是 agent_service.py:58-61 的
   NOT_FOUND_IN_KB 判据要处理的场景）。

## 本评测集的口径
· gold 用**原文片段**（evidence）+ node_id，程序化验证切片后片段完整落在某个 chunk 内。
  选 ID 而非写死 "node:chunk"：chunk 边界会随切分策略变化，写死会导致换策略后 gold 漂移。
· 指标：Hit@1 / Hit@3 / MRR（检索层）+ 拒答正确率（无答案层，检索层只能测"没乱命中"）
· 按 note_type（A/B）与 answerable（有/无）分层报告
· RAGAS 三指标（Faithfulness / Answer Relevancy / Context Recall）属**生成层**，
  需要真实 LLM 调用 + 可信 reference，本脚本不测，见文件末尾说明。

## 诚实边界
· query 仍是我写的（用户选择"我先全部出完，你再改"）⇒ **每个 case 带 query_source 字段**：
  'chatlog' = 来自真实会话记录（无偏）；'personal' = 个人语境原话（node16 交易日志）；
  'authored' = 我依据原文措辞写的（**可能偏乐观，待人工改词**）
· 45 条是规模下限，不是目标；用户改词后应扩到 200+ 再谈"基线可信"
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

OUT = BASE / 'eval' / 'eval_set_v3.json'

# note_type: A=复制/LLM总结型（规整模板）  B=手写/对话辅导型（口语、含个人语境）
# query_source: chatlog=真实会话 | personal=个人语境原话 | authored=我写的（待改词）
CASES = [
    # ================= node 1（A｜定义/特点/场景/风险 模板）=================
    ("Q01", 1, "A", "authored", "进程和线程的区别？",
     "进程是操作系统进行", "资源分配的基本单位"),
    ("Q02", 1, "A", "authored", "为什么两个线程会互相占着对方的锁不放",
     "死锁是两个或以上线程", "循环等待"),
    ("Q03", 1, "A", "authored", "多线程是怎么访问共享变量的？",
     "线程同步是协调多个线程", "信号量"),
    ("Q04", 1, "A", "authored", "为什么原子操作不能完全替代互斥锁",
     "只适用于单个变量的原子操作", "复杂逻辑仍需锁"),

    # ================= node 2（A）=================
    ("Q05", 2, "A", "authored", "vector 和 list 的区别，两者的使用场景？",
     "vector 是动态数组", "双向链表"),
    ("Q06", 2, "A", "authored", "扩容之后原来的迭代器还能用吗",
     "扩容导致迭代器失效", ""),
    ("Q07", 2, "A", "authored", "需要按键的顺序遍历，应该用哪个容器",
     "map 基于红黑树", "元素无序"),

    # ================= node 3（A｜一题一小节）=================
    ("Q08", 3, "A", "authored", "栈和堆的区别？",
     "栈空间很小", "运行时任意分配"),
    ("Q09", 3, "A", "authored", "为什么要把资源所有权转给别人",
     "移动语义", "避免昂贵拷贝"),
    ("Q10", 3, "A", "authored", "多个线程同时拷贝同一个shared_ptr安全吗",
     "引用计数的增减是原子的", ""),
    ("Q11", 3, "A", "authored", "多个线程同时改shared_ptr的指向呢",
     "多个线程同时修改同一个 shared_ptr 对象", "需要额外同步"),
    ("Q12", 3, "A", "authored", "深拷贝和浅拷贝的区别",
     "浅拷贝：只复制对象的成员值", "重新分配内存"),
    ("Q13", 3, "A", "authored", "四种类型转换的区别",
     "reinterpret_cast：底层二进制重解释", ""),
    ("Q14", 3, "A", "authored", "基类析构函数为什么一般都写成虚函数",
     "delete 基类指针时能正确先调派生类析构", ""),
    ("Q15", 3, "A", "authored", "RAII 的作用，解决了什么问题？",
     "将资源生命周期与对象生命周期绑定", ""),

    # ================= node 5（A｜后端项目各模块）=================
    ("Q16", 5, "A", "authored", "事件为什么要先在内存里排队再交给下游处理",
     "解耦 I/O 线程和处理线程", ""),
    ("Q17", 5, "A", "authored", "限流为什么要用 Lua 脚本而不是直接 INCR 加 EXPIRE",
     "INCR 和 EXPIRE 分两步非原子", "原子执行"),
    ("Q18", 5, "A", "authored", "监控数据是怎么被外部拉走的",
     "Prometheus 每 15 秒爬取", "拉模型"),
    ("Q19", 5, "A", "authored", "监控为什么用原子变量而不是加锁",
     "只读 11 个 atomic 计数器", ""),
    ("Q20", 5, "A", "authored", "怎么处理粘包和拆包",
     "先读 4 字节 header", "循环切分粘包"),
    ("Q21", 5, "A", "authored", "为什么只开两个 I/O 线程而不是其他数量",
     "瓶颈在 Redis/ClickHouse", "不在 CPU"),
    ("Q22", 5, "A", "authored", "Redis 挂掉的时候限流会失效吗",
     "Redis failure 走 fail-open", ""),
    ("Q23", 5, "A", "authored", "数据是攒一批再写还是来一条写一条",
     "内部维护 buffer", "批量 flush"),
    ("Q24", 5, "A", "authored", "Kafka 和 ClickHouse 在这里分别干什么",
     "Kafka 是流", "ClickHouse 是存"),

    # ================= node 7（A）=================
    ("Q25", 7, "A", "authored", "https是怎么保护数据的",
     "TLS 握手阶段使用非对称加密交换密钥", "对称加密"),
    ("Q26", 7, "A", "authored", "GET 和 POST 在语义上有什么区别",
     "GET 是幂等的", "POST 是非幂等的"),
    ("Q27", 7, "A", "authored", "接口报错的时状态码是多少",
     "4xx 客户端错误", "5xx 服务端错误"),

    # ================= node 8（A｜无 ## 标题，纯编号 + 缩进）=================
    ("Q28", 8, "A", "authored", "数组和链表的区别",
     "数组是连续内存的线性表", "链表通过指针连接节点"),
    ("Q29", 8, "A", "authored", "哈希冲突一般怎么解决",
     "链地址法或开放地址法", ""),
    ("Q30", 8, "A", "authored", "BFS 一般用什么数据结构",
     "BFS 广度优先搜索用队列", ""),

    # ================= node 12/13（B｜个人教学语气、表格、无 ## 标题）=================
    ("Q31", 12, "B", "authored", "为什么要三次握手，两次为什么不行",
     "三次刚好让双方都确认了彼此的收发能力", "四次多余"),
    ("Q32", 12, "B", "chatlog", "为什么要三次握手",
     "三次刚好让双方都确认了彼此的收发能力", "四次多余"),
    ("Q33", 12, "B", "chatlog", "TCP三次握手是什么", "三次刚好让双方都确认", ""),
    ("Q34", 13, "B", "authored", "一个线程怎么同时盯住成千上万个连接",
     "一个线程同时监控多个 fd", ""),
    ("Q35", 13, "B", "authored", "select 和 epoll 的区别",
     "select/poll 每次全量扫描", "只通知就绪的 fd"),
    ("Q36", 13, "B", "authored", "为什么连接数一多，遍历就不行了",
     "内核遍历所有 fd 检查", ""),

    # ================= node 14（B｜对话辅导型，含个人错误记录）=================
    ("Q37", 14, "B", "authored", "static 全局变量的作用域是什么",
     "只能在当前文件使用", "内部链接"),
    ("Q38", 14, "B", "authored", "static 局部变量和普通局部变量有什么不一样",
     "普通局部变量", "程序整个运行期间"),
    # ⚠️ 2026-10-10 修正：原题问"为什么 static 局部变量不是线程安全的"，
    # 但 node14 **完全没有讨论线程安全**（它只讲作用域/生命周期/初始化次数）。
    # 生成层评测因此出现"模型正确拒答"却被判 faithful=0.64 的假阴性。
    # 这是评测集第 6 条被发现的坏 gold（前 5 条在首轮 gold 校验中被拦下）。
    ("Q39", 14, "B", "authored", "static 局部变量的生命周期和作用域分别是什么",
     "生命周期（lifetime）：程序启动到结束", "作用域（scope）：只在函数内可见"),

    # ================= node 17（B｜口语化教学 + 表格）=================
    ("Q40", 17, "B", "authored", "define 和 const 的区别",
     "define 是文本替换", "没有类型"),
    ("Q41", 17, "B", "authored", "define 的 SQUARE 宏为什么会算错",
     "展开成 1 + 1 * 1 + 1 = 3", ""),

    # ================= node 16（B｜个人实战日志，唯一带个人语境的笔记）=================
    # 注意：本笔记里**没有**"减仓/现金余额"这类内容。原 Q42/Q44 是我凭印象写的，
    # 被 gold 验证拦下（evidence 在原文中不存在）。改为与原文对齐的 3 条。
    ("Q42", 16, "B", "personal", "那天 AI 建议我买茅台的时候有多大把握",
     "置信度 70%", ""),
    ("Q43", 16, "B", "personal", "那天茅台买在什么价位",
     "茅台 | 100 | 1324", ""),
    ("Q44", 16, "B", "personal", "那天系统扫描出了哪些超卖的股票",
     "RSI极度超卖", ""),

    # ================= 无答案层（测拒答：库里确实没有）=================
    # 注意：这类条目 evidence 为空，判据是"不该被当成笔记内容答出来"
    # 危险度分两档：
    #   OUT_OF_SCOPE  与库内容无关 → 余弦低，模型容易识别
    #   NEAR_MISS     话题相邻但不完整/时间不匹配 → 余弦高，**危险在这类**
    # 2026-10-10 从 3 条扩到 9 条：首轮实测 NEAR_MISS 只有 1/3 拒答，
    # 其中 N01 是**时效性幻觉**（把 5/20 的指数当"今天"报出，且 faithfulness=1.00）。
    ("N01", None, "N", "authored", "今天上证指数收盘多少", None, None),
    ("N02", None, "N", "authored", "帮我写一份辞职信", None, None),
    ("N03", None, "N", "authored", "MySQL 的 binlog 和 redolog 的区别", None, None),
    ("N04", None, "N", "authored", "Kubernetes 的 Pod 和容器的区别", None, None),
    ("N05", None, "N", "authored", "帮我看看我昨天记录的那笔卖出赚了多少", None, None),
    # --- 2026-10-10 新增（用 node16 真实数据造，时间/范围不匹配）---
    ("N06", None, "N", "authored", "昨天大盘收盘多少", None, None),
    ("N07", None, "N", "authored", "今天系统扫描出了哪些超卖的股票", None, None),
    ("N08", None, "N", "authored", "下午两点那次的扫描信号是什么", None, None),
    ("N09", None, "N", "authored", "记录里宁德时代的买入价是多少", None, None),
    ("N10", None, "N", "personal", "我上一笔交易赚了多少钱", None, None),
    ("N11", None, "N", "authored", "帮我总结一下这周的交易情况", None, None),
]


def verify_evidence(chunks, head, tail):
    """程序化验证：gold 片段是否完整落在某个 chunk 内。

    只选 evidence 是**因为**：chunk 边界随切分策略变化，写死 "node:chunk" 会在
    换策略后 gold 漂移，导致 before/after 不可比（v1 评测踩过这个坑）。
    """
    for i, (heading, body) in enumerate(chunks):
        if head and head in body and (not tail or tail in body):
            return i
    # 宽松一次：head/tail 分别命中同一 node 的不同 chunk（跨块说明切分把答案切开了）
    hit_head = [i for i, (_, b) in enumerate(chunks) if head and head in b]
    hit_tail = [i for i, (_, b) in enumerate(chunks) if tail and tail in b]
    if head and hit_head and tail and hit_tail and set(hit_head) & set(hit_tail):
        return sorted(set(hit_head) & set(hit_tail))[0]
    return None


def load_notes() -> dict[int, tuple[str, str]]:
    """读取真实笔记。优先 MySQL（.env 声明的生产库），连不上回退 SQLite 并告警。

    为什么要回退：本机 MySQL（XAMPP）服务从未启动（3306 无监听），
    而评测必须能在当前环境跑起来；回退时明确打印数据源，避免"以为在测生产库"。
    """
    import sqlite3
    try:
        from app.database import SessionLocal
        from app.models.node import KnowledgeNode
        db = SessionLocal()
        try:
            db.get_bind().connect()
            rows = (db.query(KnowledgeNode).filter(KnowledgeNode.user_id == 1).all())
            print('[数据源] MySQL(knowledge_base)')
            return {n.id: (n.title or '', n.content or '') for n in rows}
        finally:
            db.close()
    except Exception as e:
        print(f'[MySQL 不可用] {type(e).__name__}: {str(e)[:90]}')

    path = Path.home() / '.knowledge_base' / 'knowledge.db'
    print(f'[⚠️ 回退数据源] SQLite {path.name}（2026-05 冻结件，非生产 MySQL）')
    con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        return {r[0]: (r[1] or '', r[2] or '') for r in
                con.execute('SELECT id, title, content FROM knowledge_nodes')}
    finally:
        con.close()


def main():
    from app.utils.markdown_cleaner import split_by_headings

    nodes = load_notes()

    print(f'笔记 {len(nodes)} 条；评测用例 {len(CASES)} 条\n')

    # ---- 第一步：验证 gold ----
    print('=' * 96)
    print('第 1 步：gold 可验证性检查（evidence 必须完整落在某个 chunk 内）')
    verified, gold_chunk = {}, {}
    bad = []
    for cid, nid, ntype, qsrc, query, head, tail in CASES:
        if nid is None:
            continue
        if nid not in nodes:
            bad.append((cid, nid, 'node 不存在'))
            continue
        chunks = split_by_headings(nodes[nid][1])
        idx = verify_evidence(chunks, head, tail)
        if idx is None:
            bad.append((cid, nid, f'evidence 未命中（head={head!r} tail={tail!r}）'))
        else:
            verified[cid] = True
            gold_chunk[cid] = idx
    ok_n = sum(1 for c in CASES if c[1] is not None)
    print(f'  有答案用例 {ok_n} 条，验证通过 {len(verified)} 条，失败 {len(bad)} 条')
    for cid, nid, why in bad:
        print(f'    ❌ {cid} node={nid} {why}')

    # ---- 第二步：检索评测 ----
    print('\n' + '=' * 96)
    print('第 2 步：检索层评测（生产读路径 retrieve_relevant_nodes）')

    rows = []
    for cid, nid, ntype, qsrc, query, head, tail in CASES:
        res = rag_service.retrieve_relevant_nodes(query, top_k=5, user_id=1)
        # ⚠️ chunks_per_node=2 时同一 node 会出现两次，直接 enumerate 会把名次撑大。
        # 所以名次必须按**不同 node 的首次出现顺序**计算。
        seen, order = set(), []
        for r in res:
            if r['node_id'] not in seen:
                seen.add(r['node_id'])
                order.append(r['node_id'])
        rank = (order.index(nid) + 1) if (nid is not None and nid in order) else None
        # 真正的可用性指标：含 gold evidence 的那一块有没有被返回
        want_chunk = gold_chunk.get(cid)
        chunk_hit = (nid is not None and want_chunk is not None and
                     any(r['node_id'] == nid and r.get('chunk_index') == want_chunk
                         for r in res))
        rows.append({'id': cid, 'note_type': ntype, 'query_source': qsrc, 'query': query,
                     'gold_node': nid, 'rank': rank, 'expected_chunk': want_chunk,
                     'chunk_hit': chunk_hit,
                     'top1_node': res[0]['node_id'] if res else None,
                     'top1_heading': (res[0].get('heading') or '') if res else '',
                     'top1_cos': (1 - res[0]['distance'] ** 2 / 2) if res else None})

    ans_rows = [r for r in rows if r['gold_node'] is not None]
    neg_rows = [r for r in rows if r['gold_node'] is None]

    def metrics(sub):
        n = len(sub)
        h1 = sum(1 for r in sub if r['rank'] == 1)
        h3 = sum(1 for r in sub if r['rank'] and r['rank'] <= 3)
        h5 = sum(1 for r in sub if r['rank'] and r['rank'] <= 5)
        # MRR：只对"命中了的"取 1/rank，再除以总数（未命中贡献 0）
        reciprocal = sum(1 / r['rank'] for r in sub if r['rank'])
        mrr = (reciprocal / n) if n else 0.0
        chunk_hit = sum(1 for r in sub if r['chunk_hit'])
        return n, h1, h3, h5, mrr, chunk_hit

    print(f"\n  {'分层':<26}{'n':<5}{'Hit@1':<9}{'Hit@3':<9}{'Hit@5':<9}"
          f"{'MRR':<8}{'gold块被返回':<12}")
    print('  ' + '-' * 80)
    groups = [
        ('全部（有答案）', ans_rows),
        ('A 复制/总结型', [r for r in ans_rows if r['note_type'] == 'A']),
        ('B 手写/对话型', [r for r in ans_rows if r['note_type'] == 'B']),
        ('  B·query 来自真实会话', [r for r in ans_rows if r['query_source'] == 'chatlog']),
        ('  B·query 含个人语境', [r for r in ans_rows if r['query_source'] == 'personal']),
        ('  B·query 我写的(待改词)', [r for r in ans_rows if r['query_source'] == 'authored']),
    ]
    for name, sub in groups:
        if not sub:
            continue
        n, h1, h3, h5, mrr, ch = metrics(sub)
        print(f"  {name:<26}{n:<5}{h1}/{n:<7}{h3}/{n:<7}{h5}/{n:<7}{mrr:<8.3f}"
              f"{ch}/{n}")

    print('\n  未进前 5 的用例:')
    miss = [r for r in ans_rows if not r['rank'] or r['rank'] > 5]
    for r in miss:
        print(f"    {r['id']} [{r['note_type']}] {r['query'][:34]:<36} "
              f"gold=node{r['gold_node']} rank={r['rank']} top1=node{r['top1_node']}"
              f"({r['top1_heading'][:16]})")
    if not miss:
        print('    无')

    print(f'\n  无答案层（{len(neg_rows)} 条，检索层只能看"是否乱命中"）:')
    for r in neg_rows:
        print(f"    {r['id']} {r['query'][:30]:<32} top1=node{r['top1_node']} "
              f"cos={r['top1_cos']:.3f}  ← 需人工判断是否该被当成笔记内容")

    payload = {
        'eval_set_version': 'v3',
        'created_at': '2026-10-07',
        'collection': rag_service._get_user_collection(1).name,
        'metrics': {'Hit@1': True, 'Hit@3': True, 'Hit@5': True, 'MRR': True,
                    'note': '检索层指标；生成层(RAGAS 三指标)需真实 LLM 调用，见文件头说明'},
        'layers': {name: dict(zip(('n', 'hit@1', 'hit@3', 'hit@5', 'mrr'), metrics(sub)))
                   for name, sub in groups},
        'cases': CASES,
        'results': rows,
        'evidence_verified': len(verified),
        'evidence_failed': bad,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n  已写: {OUT.name}')


if __name__ == '__main__':
    main()
