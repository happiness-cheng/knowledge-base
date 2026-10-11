"""基准 v2：在**更大且更脏**的语料上测检索，并按 cohort 分开报告。

## 为什么要 cohort 分开
真实笔记 12 条（Markdown 知识点总结，体裁单一）与合成语料 86 条（26 种脏法）
是两类不同的数据。混成一个总分毫无意义 —— 一个是"我的项目业绩"，
另一个是"抗噪压力测试"。**任何报告都必须分开写。**

## 两种评测
1. **真实 cohort**：复用 `eval_set_v3` 的 44 条（gold 在真实笔记里），
   但检索在**合并语料**（真实 57 块 + 合成 142 块）上进行。
   为什么：这才是"语料变大"后最真实的问题 —— 新笔记会不会把旧答案挤下去。
2. **合成 cohort**：新写的 24 条 query，gold 指向合成笔记，
   按 pattern 分组统计，用来定位"哪类脏法最伤检索"。

## 注意
合成 cohort 的查询**故意使用与文档不同的措辞**（含口语化），
因为实测证明"自造 query 用文档用词"会让分数虚高。
"""
import importlib.util
import statistics
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402
from app.utils.markdown_cleaner import split_by_headings  # noqa: E402

spec = importlib.util.spec_from_file_location('ev3', _BACKEND / 'eval' / 'eval_set_v3.py')
ev3 = importlib.util.module_from_spec(spec)
sys.modules['ev3'] = ev3
spec.loader.exec_module(ev3)

# ------------------------------------------------------------------ 反查真实 node_id
# ⚠️ 血证（2026-10-10）：合成 cohort 第一版我**手写 node_id** 当 gold，结果编号全错。
# 生成器按**列表顺序**编 id（`_gen_template_notes(200, _TOPICS[:10])` 把 _TOPICS 前 10 个
# 编成 200..209），而我是按**主题名**记的编号，两者错位。
# 证据：query「判断一个元素一定不存在用什么结构」我标 gold=205，而 node205 是一致性哈希、
# 真正内容是 204（布隆过滤器）；「主从延迟」我标 208，而 208 是 JWT、真内容在 207。
# **检索返回的 top1 恰恰就是正确那条 —— 检索是对的，错的是我的标注。**
# 修法：不手写 id，改从生成器**反查**标题 → node_id，找不到就抛错（不静默返回 None）。
_src = (_BACKEND / 'eval' / 'build_synthetic_corpus.py').read_text(encoding='utf-8')
_ns = {}
exec(compile(_src.split('def main()')[0], 'sc', 'exec'), _ns)
TITLE2NID = {}
for nid, title, pattern, created, content in _ns['N']:
    TITLE2NID.setdefault(title, []).append((nid, pattern))
for nid, title, pattern, created, content in _ns['_generate_bulk']():
    TITLE2NID.setdefault(title, []).append((nid, pattern))


def nid_of(title_substr, pattern=None):
    """按标题子串（可选再按 pattern）反查 node_id。找不到直接抛错，不静默返回 None。

    pattern 参数是必需的：headed 与 flat 两个巡检系列**日期相同、标题相同**，
    只有 pattern 能区分（否则会反查到错误系列，那正是第一版 gold 错标的成因之一）。
    """
    cands = [(nid, p) for title, lst in TITLE2NID.items() if title_substr in title
             for nid, p in lst]
    if pattern:
        cands = [(nid, p) for nid, p in cands if p == pattern]
    if not cands:
        raise KeyError(f'反查 node_id 失败: title={title_substr!r} pattern={pattern!r}')
    return cands[0][0]


# ---------------------------------------------------------------- 合成 cohort 查询
# (id, gold_node, pattern, query, 说明) —— gold **一律用 nid_of() 反查**，不手写数字
SYNTH_CASES = [
    # gold **一律用 nid_of(标题, pattern) 反查**，不手写数字。
    # 真实映射（由生成器决定）：布隆过滤器=204 / 读写分离延迟=207 / 幂等设计=212 /
    # 可观测性三支柱=224 / 回滚策略=227 / 线程池参数=219(messy) / 问答：缓存一致性=267
    # ---- 干净模板型 ----
    ('S01', nid_of('Redis 持久化', 'gen_clean'), 'gen_clean',
     'RDB 和 AOF 有什么区别', 'Redis 持久化'),
    ('S02', nid_of('布隆过滤器', 'gen_clean'), 'gen_clean',
     '判断一个元素一定不存在用什么结构', '布隆过滤器'),
    ('S03', nid_of('TCP 粘包', 'gen_clean'), 'gen_clean',
     'TCP 怎么会粘包，怎么解', 'TCP 粘包'),
    ('S04', nid_of('读写分离延迟', 'gen_clean'), 'gen_clean',
     '主从延迟导致读到旧数据怎么办', '读写分离延迟'),
    # ---- 脏结构型（缩进标题 + 无空行 + 口语尾巴）----
    ('S05', nid_of('乐观锁与悲观锁', 'gen_messy'), 'gen_messy',
     '乐观锁和悲观锁什么场景用哪个', '乐观锁悲观锁'),
    ('S06', nid_of('限流算法', 'gen_messy'), 'gen_messy',
     '限流那几个算法怎么挑', '限流算法（非问答版）'),
    ('S07', nid_of('幂等设计', 'gen_messy'), 'gen_messy',
     '怎么保证重复请求不会重复扣款', '幂等设计（非问答版）'),
    ('S08', nid_of('线程池参数', 'gen_messy'), 'gen_messy',
     '线程池那几个参数怎么定', '线程池参数'),
    # ---- 深层结构型（### 子层）----
    ('S09', nid_of('可观测性三支柱', 'gen_deep'), 'gen_deep',
     '可观测性三个东西分别解决什么', '可观测性三支柱'),
    ('S10', nid_of('SLA 与 SLO', 'gen_deep'), 'gen_deep',
     '对外承诺和内部目标怎么区分', 'SLA 与 SLO'),
    ('S11', nid_of('回滚策略', 'gen_deep'), 'gen_deep',
     '回滚脚本要不要提前演练', '回滚策略'),
    ('S12', nid_of('日志分级', 'gen_deep'), 'gen_deep',
     '什么级别的日志才该触发告警', '日志分级'),
    # ---- 事故日志型：headed 与 flat 两系列日期相同、内容不同，只能靠 pattern 区分 ----
    ('S13', nid_of('巡检记录 2026-08-01', 'gen_incident_headed'), 'gen_incident_headed',
     '8月1号巡检发现了什么问题', 'headed 第 1 条（磁盘告警）'),
    ('S14', nid_of('巡检记录 2026-08-10', 'gen_incident_headed'), 'gen_incident_headed',
     '8月10号巡检发现了什么问题', 'headed 最后一条'),
    ('S15', nid_of('巡检记录 2026-08-01', 'gen_incident_flat'), 'gen_incident_flat',
     '网关 502 比例升高那次怎么处置的', 'flat 第 1 条（与 headed 同日不同内容）'),
    # ---- 问答对型 + 消歧（同主题两份笔记，看能否命中指定那份）----
    ('S16', nid_of('问答：一致性哈希', 'gen_qa_clean'), 'gen_qa_clean',
     '问答笔记里怎么讲一致性哈希的', '一致性哈希'),
    ('S17', nid_of('问答：OOM 排查', 'gen_qa_flat'), 'gen_qa_flat',
     '问答笔记里 OOM 怎么排查', 'OOM 排查'),
    ('S18', nid_of('问答：限流算法', 'gen_qa_flat'), 'gen_qa_flat',
     '问答版里限流怎么讲', '限流算法（问答版，与 S06 同主题）'),
    # ---- 手写脏法专项 ----
    ('S19', nid_of('分布式系统设计'), 'pdf_paste',
     'CAP 定理到底在说什么', 'PDF 粘贴含页眉残留'),
    ('S20', nid_of('重试装饰器'), 'code_only',
     '重试怎么实现，什么错误不该重试', '纯代码笔记'),
    ('S21', nid_of('性能问题排查记录'), 'no_heading',
     '接口变慢应该先看什么指标', '无标题长文'),
    ('S22', nid_of('死锁（第二份笔记'), 'duplicate_topic',
     '死锁怎么预防最省事', '与 node1 重复的主题'),
    ('S23', nid_of('索引失效'), 'tutor_dialogue',
     '加了索引为什么不走索引', '对话辅导型'),
    ('S24', nid_of('线上事故复盘 2026-09-11'), 'recent_incident',
     '9月11号那次故障是什么原因', '较新的事故'),
    ('S25', nid_of('线上事故复盘 2026-03-02'), 'stale_incident',
     '3月2号那次故障是什么原因', '较旧的事故'),
    ('S26', nid_of('MVCC（口语版'), 'personal_voice',
     'MVCC 到底还要不要加锁', '口语化笔记'),
    ('S27', nid_of('微服务治理全景'), 'very_long',
     '灰度回滚慢算不算问题', '超长笔记的尾部'),
]


def metrics(rows, key='rank'):
    n = len(rows)
    if not n:
        return 0, 0, 0, 0.0
    h1 = sum(1 for r in rows if r[key] == 1)
    h3 = sum(1 for r in rows if r[key] and r[key] <= 3)
    h5 = sum(1 for r in rows if r[key] and r[key] <= 5)
    mrr = sum(1 / r[key] for r in rows if r[key]) / n
    return h1, h3, h5, mrr


def main():
    synth_col = rag_service.chroma_client.get_collection(
        name=rag_service.get_collection_name(1, '_synth'))
    prod_col = rag_service._get_user_collection(1)
    print(f'真实集合 {prod_col.name}: {prod_col.count()} 块')
    print(f'合成集合 {synth_col.name}: {synth_col.count()} 块\n')

    # 合并池：真实 + 合成（模拟"语料变大"）
    import numpy as np

    # ⚠️ 为什么不用 col.get(include=['embeddings'])（2026-10-10 实测）
    # ChromaDB 1.5.9 把向量存在 HNSW 的 .bin 文件里（不在 sqlite），
    # 读向量路径**间歇性失败**：同一批集合、同一段代码，时而
    # `Error creating hnsw segment reader: Nothing found on disk`，时而正常。
    # 而 `include=['documents','metadatas']` 一直可靠。
    # 所以改为：读文本 + **现场重新编码**。199 块约 1 分钟，换来可复现。
    model = rag_service._get_model()

    def load(col):
        d = col.get(include=['documents', 'metadatas'])
        texts, metas_ = [], []
        for cid, doc, meta in zip(d['ids'], d['documents'], d['metadatas']):
            title = meta.get('title', '')
            heading = meta.get('heading', '')
            texts.append(f'{title}\n{heading}\n{doc}' if title else f'{heading}\n{doc}')
            metas_.append(meta)
        embs_ = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return d['ids'], np.asarray(embs_, dtype=np.float32), metas_

    ids_r, emb_r, meta_r = load(prod_col)
    ids_s, emb_s, meta_s = load(synth_col)
    ids = list(ids_r) + list(ids_s)
    embs = np.vstack([emb_r, emb_s])
    metas = list(meta_r) + list(meta_s)
    print(f'合并池 {len(ids)} 块（真实 {len(ids_r)} + 合成 {len(ids_s)}）\n')

    def retrieve(query, chunks_per_node=2, top_k=3):
        qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
        order = np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))
        grouped, seq = {}, []
        for idx in order:
            nid = metas[idx]['node_id']
            if len(grouped.get(nid, [])) >= chunks_per_node:
                continue
            if nid not in grouped:
                grouped[nid] = []
                seq.append(nid)
            grouped[nid].append(int(idx))
            if len(seq) >= top_k and all(len(grouped[x]) >= chunks_per_node
                                         for x in seq[:top_k]):
                break
        out = []
        for nid in seq[:top_k]:
            out.extend(grouped[nid])
        return out

    # ---- 真实 cohort：44 条在合并池上 ----
    print('=' * 88)
    print('COHORT A · 真实笔记的 44 条 query（在"真实+合成"合并池上检索）')
    split_cache = {nid: split_by_headings(c) for nid, (t, c) in ev3.load_notes().items()}
    rows = []
    for cid, nid, ntype, qsrc, query, head, tail in ev3.CASES:
        if nid is None:
            continue
        want = ev3.verify_evidence(split_cache[nid], head, tail)
        idxs = retrieve(query)
        node_seq = []
        for i in idxs:
            if metas[i]['node_id'] not in node_seq:
                node_seq.append(metas[i]['node_id'])
        rank = (node_seq.index(nid) + 1) if nid in node_seq else None
        chunk_hit = any(metas[i]['node_id'] == nid and metas[i].get('chunk_index') == want
                        for i in idxs)
        rows.append({'id': cid, 'rank': rank, 'chunk_hit': chunk_hit,
                     'from_synth': any(metas[i].get('synthetic') for i in idxs)})
    h1, h3, h5, mrr = metrics(rows)
    ch = sum(1 for r in rows if r['chunk_hit'])
    print(f'  node Hit@1 {h1}/{len(rows)}  Hit@3 {h3}/{len(rows)}  Hit@5 {h5}/{len(rows)}  '
          f'MRR {mrr:.3f}')
    print(f'  gold块被返回 {ch}/{len(rows)} = {ch / len(rows):.3f}')
    polluted = [r['id'] for r in rows if r['from_synth']]
    print(f'  返回结果里混入合成块的用例数：{len(polluted)}/{len(rows)}'
          f'{"（" + ",".join(polluted[:8]) + "）" if polluted else ""}')

    # ---- 合成 cohort ----
    print('\n' + '=' * 88)
    print('COHORT B · 合成语料的 24 条 query（测抗噪与体裁鲁棒性）')
    print(f'{"ID":<5}{"gold":<6}{"rank":<6}{"块命中":<8}{"pattern":<22}query')
    print('-' * 88)
    srows = []
    for cid, gold, pattern, query, note in SYNTH_CASES:
        idxs = retrieve(query)
        node_seq = []
        for i in idxs:
            if metas[i]['node_id'] not in node_seq:
                node_seq.append(metas[i]['node_id'])
        rank = (node_seq.index(gold) + 1) if gold in node_seq else None
        hit = any(metas[i]['node_id'] == gold for i in idxs)
        srows.append({'id': cid, 'rank': rank, 'pattern': pattern,
                      'chunk_hit': hit, 'gold': gold, 'query': query,
                      'top1': metas[idxs[0]]['node_id'] if idxs else None})
        print(f'{cid:<5}{gold:<6}{str(rank):<6}{("是" if hit else "否"):<8}'
              f'{pattern:<22}{query[:34]}')
    h1, h3, h5, mrr = metrics(srows)
    print('-' * 88)
    print(f'  node Hit@1 {h1}/{len(srows)}  Hit@3 {h3}/{len(srows)}  Hit@5 {h5}/{len(srows)}  '
          f'MRR {mrr:.3f}')

    # ⚠️ 必须同时报"答案块进上下文"（2026-10-11 修正）
    # 只报 node Hit@1 会把"gold 排第 2"当成失败，而排第 2 时答案**已经在上下文里**了。
    # 后果实测：gen_messy 按 Hit@1 显示 1/4（最差），但按"答案块进上下文"是 3/4，
    # 与其它 pattern 同档；真正的失败只有 S07 一条。
    # 两个口径回答的是不同问题：
    #   Hit@1 = "我指定的那份笔记排第 1 了吗"（受 gold 指向哪一份影响）
    #   答案块进上下文 = "用户拿到答案了吗"（用户关心的量）
    print('\n  按脏法分组（同时给两个口径 —— 只看 Hit@1 会误判"整类脏法失效"）:')
    print(f'    {"pattern":<24}{"n":<4}{"Hit@1":<10}{"Hit@3":<10}{"MRR":<9}答案块进上下文')
    by = {}
    for r in srows:
        by.setdefault(r['pattern'], []).append(r)
    for p, sub in sorted(by.items(), key=lambda kv: -len(kv[1])):
        h1_, h3_, _, mrr_ = metrics(sub)
        ck_ = sum(1 for r in sub if r['chunk_hit'])
        print(f'    {p:<24}{len(sub):<4}{h1_}/{len(sub):<8}{h3_}/{len(sub):<8}'
              f'{mrr_:<9.3f}{ck_}/{len(sub)} = {ck_ / len(sub):.3f}')

    print('\n  未命中明细:')
    for r in srows:
        if not r['rank'] or r['rank'] > 3:
            # 区分"没进上下文"（用户拿不到答案）与"没排第 1"（照样拿得到）
            kind = '没进上下文' if not r['chunk_hit'] else f"进上下文但排第{r['rank']}"
            print(f"    {r['id']} gold={r['gold']} rank={r['rank']} top1={r['top1']} "
                  f"[{kind}]  {r['query']}")

    print('\n' + '=' * 88)
    print('对照（同一批合成 query，但在**只有合成语料**的池里检索）:')
    embs2, metas2 = emb_s, meta_s

    def retrieve_synth_only(query, chunks_per_node=2, top_k=3):
        qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
        order = np.argsort(np.linalg.norm(embs2 - qv[None, :], axis=1))
        grouped, seq = {}, []
        for idx in order:
            nid = metas2[idx]['node_id']
            if len(grouped.get(nid, [])) >= chunks_per_node:
                continue
            if nid not in grouped:
                grouped[nid] = []
                seq.append(nid)
            grouped[nid].append(int(idx))
            if len(seq) >= top_k and all(len(grouped[x]) >= chunks_per_node
                                         for x in seq[:top_k]):
                break
        out = []
        for nid in seq[:top_k]:
            out.extend(grouped[nid])
        return out

    rows2 = []
    for cid, gold, pattern, query, note in SYNTH_CASES:
        idxs = retrieve_synth_only(query)
        node_seq = [metas2[i]['node_id'] for i in idxs]
        ded = []
        for n in node_seq:
            if n not in ded:
                ded.append(n)
        rows2.append({'rank': (ded.index(gold) + 1) if gold in ded else None})
    h1b, h3b, h5b, mrrb = metrics(rows2)
    print(f'  纯合成池：Hit@1 {h1b}/{len(rows2)}  Hit@3 {h3b}/{len(rows2)}  MRR {mrrb:.3f}')
    print(f'  合并池  ：Hit@1 {h1}/{len(srows)}  Hit@3 {h3}/{len(srows)}  MRR {mrr:.3f}')
    print('  ⇒ 差值 = "被真实笔记干扰"造成的损失（或反之）')


if __name__ == '__main__':
    main()
