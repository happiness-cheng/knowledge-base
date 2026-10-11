"""取证 2：node 配额分配造成的损失 vs gold 标错版本造成的损失。

## 两个必须分开的量（bench_v2 把它们混成一个 rank，所以看不出真相）
A. **能力问题**：真正含答案的笔记，有没有进 top_k？—— 这才是用户会不会拿到答案。
B. **标注问题**：我**指定的那一份**笔记有没有进 top_k？—— 这受"我给哪一份当 gold"影响。

实测（diag_messy）：S05/S06/S07 的 query 都在问"**该用时/怎么挑**"，
而 gen_messy 模板**没有 场景 字段**、gen_qa 模板**有**（"追问: 什么场景用"）。
⇒ 检索命中"问答版"是**正确行为**，是 gold 指错了版本。

## 配额分配问题（独立于上面的标注问题）
`retrieve_relevant_nodes` 收集够 top_k 个 node 就 break，再取 order[:top_k]。
于是 **node 的第 2 块可以比第 4 个 node 的第 1 块更相关，但第 4 个 node 占着名额**。
实测 S07：node104（死锁，cos 0.4593）只比 gold node212（cos 0.4592）高 **0.0001**，
却把 gold 挤出了 top3 —— 一个 node 名额被约等分的噪声占掉。

## 本脚本做什么
1. 对每条用例计算 accept 集合（真正含答案的所有版本），给出 A 类指标。
2. 计算"若按块级全局排序取 top_k 个 node"（即放宽 node 名额、看更远的 node）
   是否能修复 B 类失败 —— 用来判断配额分配值不值得改。
"""
import importlib.util
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

spec = importlib.util.spec_from_file_location('b2', _BACKEND / 'eval' / 'bench_v2.py')
b2 = importlib.util.module_from_spec(spec)
sys.modules['b2'] = b2
spec.loader.exec_module(b2)

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
d = col.get(include=['documents', 'metadatas'])
metas, docs = d['metadatas'], d['documents']
model = rag_service._get_model()

texts = []
for doc, m in zip(docs, metas):
    t, h = m.get('title', ''), m.get('heading', '')
    texts.append(f'{t}\n{h}\n{doc}' if t else f'{h}\n{doc}')
embs = np.asarray(model.encode(texts, normalize_embeddings=True,
                               show_progress_bar=False), dtype=np.float32)

# ---------------- accept 集合：真正含答案的所有版本，程序化判定（不手写） ----------------
# 判据：同一"主题字段 k"（_TOPICS 的 k 是主题唯一标识）生成的所有版本都含该主题正文。
# gen_messy 缺 scene、gen_clean/gen_qa 含 scene ⇒ 按 query 问什么决定谁该被接受。
# 这里用**保守判据**：只要笔记正文里出现了 gold 笔记的"定义句"前 20 字，就算同答案。
GOLD_TEXT = {}
for cid, gold, pattern, query, note in b2.SYNTH_CASES:
    GOLD_TEXT[cid] = '\n'.join(
        docs[i] for i in range(len(metas)) if metas[i]['node_id'] == gold)


def same_answer_nodes(cid):
    """找出所有"含与 gold 相同定义句"的 node —— 即同主题的另一份笔记。"""
    g = GOLD_TEXT[cid]
    # 取 gold 里第一句实质性内容作为指纹（跳过标题行）
    probe = ''
    for line in g.split('\n'):
        s = line.strip().lstrip('-*· ').strip()
        if len(s) > 12:
            probe = s[:20]
            break
    if not probe:
        return []
    out = []
    for nid in {m['node_id'] for m in metas}:
        txt = '\n'.join(docs[i] for i in range(len(metas)) if metas[i]['node_id'] == nid)
        if probe and probe in txt:
            out.append(nid)
    return sorted(out)


def retrieve(query, top_k=3, chunks_per_node=2):
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    order = np.argsort(dist)
    grouped, seq = {}, []
    for idx in order:
        nid = metas[idx]['node_id']
        if len(grouped.get(nid, [])) >= chunks_per_node:
            continue
        if nid not in grouped:
            grouped[nid] = []
            seq.append(nid)
        grouped[nid].append(int(idx))
        if len(seq) >= top_k and all(len(grouped[x]) >= chunks_per_node for x in seq[:top_k]):
            break
    return seq  # 只关心 node 序列


def rank_of(query, cands, top_k=3):
    seq = retrieve(query, top_k=top_k)
    for n in cands:
        if n in seq:
            return seq.index(n) + 1
    return None


print('=' * 100)
print('18 个"每个 pattern 一条"的用例：gold 标错版本了没有？')
print('=' * 100)
print(f'{"ID":<5}{"gold":<7}{"accept集合（真正含答案的所有版本）":<38}'
      f'{"gold排名":<9}{"accept最佳排名"}')
print('-' * 100)
labeled_wrong, capability_fail = [], []
for cid, gold, pattern, query, note in b2.SYNTH_CASES:
    acc = same_answer_nodes(cid)
    r_gold = rank_of(query, [gold])
    r_acc = rank_of(query, acc)
    flag = ''
    if r_gold != 1 and r_acc == 1:
        flag = ' ← gold 标错版本'
        labeled_wrong.append(cid)
    elif r_acc != 1:
        flag = ' ← 真失败'
        capability_fail.append(cid)
    print(f'{cid:<5}{gold:<7}{str(acc):<38}{str(r_gold):<9}{str(r_acc)}{flag}')

print()
print(f'因 gold 指向版本而误判为失败：{len(labeled_wrong)} 条 {labeled_wrong}')
print(f'真正取不到答案（accept 集合也没进 top3）：{len(capability_fail)} 条 {capability_fail}')

# ---------------- 配额分配：把 top_k 放大看 gold 在第几个 node ----------------
print()
print('=' * 100)
print('配额分配：放宽 node 名额后，失败用例的 gold 出现在第几个 node？')
print('=' * 100)
print(f'{"ID":<5}{"gold":<7}{"rank@k=3":<10}{"rank@k=10":<11}{"rank@k=20":<11}'
      f'{"gold最好的块全库块级排名"}')
print('-' * 100)
for cid, gold, pattern, query, note in b2.SYNTH_CASES:
    r3 = rank_of(query, [gold], top_k=3)
    r10 = rank_of(query, [gold], top_k=10)
    r20 = rank_of(query, [gold], top_k=20)
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    dist = np.linalg.norm(embs - qv[None, :], axis=1)
    gidx = [i for i in range(len(metas)) if metas[i]['node_id'] == gold]
    blk = int(np.argsort(dist).tolist().index(min(gidx, key=lambda i: dist[i]))) + 1
    if r3 == 1:
        continue
    print(f'{cid:<5}{gold:<7}{str(r3):<10}{str(r10):<11}{str(r20):<11}{blk}')
