"""knowledge-base RAG 基线评测（改造前：MiniLM 384维，无 size 兜底时代语料）
评测集 v0.9：14 条查询（短笔记6 + 长文档4 + 外部语料4），分层报告
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import numpy as np
from sentence_transformers import SentenceTransformer

LAYER_OF = {"short": "短笔记", "long": "长文档", "external": "外部语料"}

# 评测集：expected 标注 short 层用 node_id 数字；chunked 层用 source_file
# 查询纪律：零重词（不出现文档标题原词）
CASES = [
    # --- 短笔记层（6条）---
    {"id": "S01", "layer": "short", "expected": 1,
     "query": "一个程序里同时跑多个执行流，进程和线程在占用资源、切换开销上有什么不同？",
     "note": "node1 进程与线程区别（09-09 标注修正：原查询问内存布局，node1 实际讲进程线程）"},
    {"id": "S02", "layer": "short", "expected": 2,
     "query": "C++里面那些常用的数据容器，比如能自动扩容的数组、红黑树实现的映射，都讲讲",
     "note": "node2 C++ STL容器"},
    {"id": "S03", "layer": "short", "expected": 7,
     "query": "网站地址栏变成 https 之后，数据在传输时做了哪些额外的安全处理？",
     "note": "node7 HTTP协议基础（09-09 标注修正：node7 正文实际讲请求方法+HTTPS，原查询问报文结构但正文没有该内容）"},
    {"id": "S04", "layer": "short", "expected": 12,
     "query": "建立可靠连接的时候为什么握手要来三个回合，两个不行吗？",
     "note": "node12 三次握手"},
    {"id": "S05", "layer": "short", "expected": 14,
     "query": "C++里那个让变量活得跟程序一样久的关键字，在类里和函数里用法有什么区别？",
     "note": "node14 static"},
    {"id": "S06", "layer": "short", "expected": 17,
     "query": "编译期常量和预处理宏定义一个数值的时候，用哪个更好，两种方式有什么不一样？",
     "note": "node17 const VS define"},
    # --- 长文档层（4条）---
    {"id": "L01", "layer": "long", "expected": "ai-trader架构.md",
     "query": "那个自动炒股系统从收到行情到下单，中间的数据都流经哪些模块？",
     "note": "ai-trader架构.md 数据流"},
    {"id": "L02", "layer": "long", "expected": "ai-trader使用说明.md",
     "query": "怎么设置系统最多同时持有几只股票、单只最多买多少钱的仓位？",
     "note": "ai-trader使用说明.md 风控规则"},
    {"id": "L03", "layer": "long", "expected": "knowledge-base项目总结.md",
     "query": "这个知识库项目里AI是怎么决定要不要查资料的，循环跑多少步会停？",
     "note": "kb项目总结 ReAct循环"},
    {"id": "L04", "layer": "long", "expected": "knowledge-base项目总结.md",
     "query": "知识库里笔记和笔记之间的自动关联是用什么方法找出来的，要花钱吗？",
     "note": "kb项目总结 知识图谱自动关联"},
    # --- 外部语料层（4条）---
    {"id": "X01", "layer": "external", "expected": "负载均衡.md",
     "query": "服务器流量特别大的时候，怎么把请求合理地分摊到多台机器上？有哪些分配策略？",
     "note": "外部：负载均衡"},
    {"id": "X02", "layer": "external", "expected": "SQL优化.md",
     "query": "数据库查询跑得很慢，从索引和语句写法的角度怎么让它快起来？",
     "note": "外部：SQL优化"},
    {"id": "X03", "layer": "external", "expected": "面向切面编程AOP.md",
     "query": "想在业务代码外面统一加上日志和权限校验，不改动函数本身，这种编程思想叫什么？",
     "note": "外部：AOP"},
    {"id": "X04", "layer": "external", "expected": "Git多用户配置.md",
     "query": "一台电脑上要同时用公司账号和个人账号提交代码，怎么区分身份？",
     "note": "外部：Git多用户"},
    # --- 扩充语料后新增（14条：Redis/分布式/消息队列/缓存/OS/网络层/传输层/应用层/MySQL/Docker/Socket/系统设计/进程/死锁）---
    {"id": "X05", "layer": "external", "expected": "Redis.md",
     "query": "把数据放在内存里做高速读写的那种键值存储，有哪几种常用的数据类型和应用场景？",
     "note": "外部：Redis"},
    {"id": "X06", "layer": "external", "expected": "分布式.md",
     "query": "好几个服务分散在不同机器上协作，怎么保证它们对一个关键操作只执行一次？",
     "note": "外部：分布式"},
    {"id": "X07", "layer": "external", "expected": "消息队列.md",
     "query": "服务之间不想直接互相调用、想解耦开来，把任务先囤起来慢慢处理，用什么中间件？",
     "note": "外部：消息队列"},
    {"id": "X08", "layer": "external", "expected": "缓存.md",
     "query": "大量用户同时请求一个热点数据，数据库扛不住，怎么在前面挡一层？",
     "note": "外部：缓存"},
    {"id": "X09", "layer": "external", "expected": "计算机操作系统 - 进程管理.md",
     "query": "操作系统怎么决定哪个程序先占用处理器，调度的时候都考虑什么？",
     "note": "外部：进程管理"},
    {"id": "X10", "layer": "external", "expected": "计算机操作系统 - 死锁.md",
     "query": "两个程序各自握着一个资源不放、都在等对方，这种情况怎么预防和处理？",
     "note": "外部：死锁"},
    {"id": "X11", "layer": "external", "expected": "计算机网络 - 传输层.md",
     "query": "网络通信里靠什么区分同一台机器上不同的应用程序？",
     "note": "外部：传输层"},
    {"id": "X12", "layer": "external", "expected": "计算机网络 - 网络层.md",
     "query": "数据包从你的电脑跨过好多个路由器到达远方服务器，中间是靠什么找路的？",
     "note": "外部：网络层"},
    {"id": "X13", "layer": "external", "expected": "MySQL.md",
     "query": "关系型数据库里那棵用来加速查找的树状结构，为什么用这种树而不用别的树？",
     "note": "外部：MySQL索引"},
    {"id": "X14", "layer": "external", "expected": "Docker.md",
     "query": "怎么把一个程序连同它的运行环境一起打包成轻量的、到哪都能跑的容器？",
     "note": "外部：Docker"},
    {"id": "X15", "layer": "external", "expected": "Socket.md",
     "query": "两个程序想隔着网络直接收发字节流，编程接口上一般怎么建立这条通道？",
     "note": "外部：Socket"},
    {"id": "X16", "layer": "external", "expected": "系统设计基础.md",
     "query": "设计一个大用户量的互联网服务，一开始就要考虑的横纵向扩展、拆分思路有哪些？",
     "note": "外部：系统设计基础"},
    # --- 长文档层扩充（2条）---
    {"id": "L05", "layer": "long", "expected": "Agent学习追踪文档.md",
     "query": "RAG 的检索阶段失败有哪几类原因，按什么顺序逐段排查定位？",
     "note": "Agent追踪文档 排查链"},
    {"id": "L06", "layer": "long", "expected": "操作系统概述(长文).md",
     "query": "内核态和用户态是什么，为什么要有这两种运行模式的切换？",
     "note": "长文：OS概述 内核态用户态"},
]


def corpus_lookup():
    """返回 short_id→doc 和 chunked_source→[chunks]"""
    short = {d['node_id']: d for d in json.load(open('eval/corpus_short.json', encoding='utf-8'))}
    chunked = json.load(open('eval/corpus_chunked.json', encoding='utf-8'))
    by_source = {}
    for c in chunked:
        by_source.setdefault(c['source_file'], []).append(c)
    return short, by_source


def evaluate(model_name: str, model, query_prefix: str = ''):
    """全库（12短+55chunks=67条）评测，返回分层指标"""
    short, by_source = corpus_lookup()
    # 文档池：短笔记(标题拼正文) + 全部chunks(标题拼正文)
    docs = []  # (layer, key, embed_text)
    for nid, d in short.items():
        docs.append(("short", nid, f"{d['title']}\n{d['content']}"))
    for src, chunks in by_source.items():
        for c in chunks:
            docs.append(("long" if src.endswith(('架构.md', '说明.md', '总结.md')) else "external",
                         src, f"{c['chunk_title']}\n{c['content']}"))

    texts = [t for _, _, t in docs]
    embs = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)

    layers = {v: {"recall@3": 0, "mrr": 0.0, "n": 0, "details": []} for v in LAYER_OF.values()}
    overall = {"recall@3": 0, "mrr": 0.0}

    for case in CASES:
        q = model.encode([query_prefix + case['query']], normalize_embeddings=True)[0]
        sims = embs @ q
        order = np.argsort(-sims)

        # 找目标在排名中的位置（short 按 node_id；chunked 按来源文件——任一chunk命中算）
        best_rank = None
        for r, idx in enumerate(order, 1):
            layer, key, _ = docs[idx]
            if case['layer'] == 'short' and layer == 'short' and key == case['expected']:
                best_rank = r
                break
            if case['layer'] != 'short' and key == case['expected']:
                best_rank = r
                break

        ly = LAYER_OF[case['layer']]
        hit3 = best_rank is not None and best_rank <= 3
        mrr = 0.0 if best_rank is None else 1.0 / best_rank
        layers[ly]["recall@3"] += hit3
        layers[ly]["mrr"] += mrr
        layers[ly]["n"] += 1
        top1 = docs[order[0]]
        layers[ly]["details"].append({
            "id": case['id'], "expected": case['expected'],
            "rank": best_rank, "recall3": hit3,
            "top1": f"{top1[1]}({top1[0]})",
        })
        overall["recall@3"] += hit3
        overall["mrr"] += mrr

    n = len(CASES)
    result = {
        "model": model_name, "query_prefix": bool(query_prefix),
        "n_docs": len(docs), "n_cases": n,
        "recall@3": round(overall["recall@3"] / n, 3),
        "mrr": round(overall["mrr"] / n, 3),
        "layers": {
            v: {"recall@3": f"{d['recall@3']}/{d['n']}",
                "mrr": round(d['mrr'] / d['n'], 3) if d['n'] else 0,
                "details": d['details']}
            for v, d in layers.items() if d['n']
        },
    }
    return result


if __name__ == '__main__':
    import os
    os.environ['HF_HUB_OFFLINE'] = '0'  # 允许下载
    model = SentenceTransformer('all-MiniLM-L6-v2')  # 改造前基线模型
    result = evaluate('all-MiniLM-L6-v2', model)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    with open('eval/baseline_kb_before.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print('\n已保存: eval/baseline_kb_before.json')
