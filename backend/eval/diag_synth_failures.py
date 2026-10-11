"""取证：合成 cohort 的失败到底是"数据同质"还是"gold 标错"？

不再猜。对每条未命中的用例，把 **gold 笔记原文** 与 **实际 top1 笔记原文** 并排打印，
并检查"该 query 的特征词在 gold 里是否真的存在"。
若能看出 gold 里根本没有 query 要的东西 → 是我的基准写错（第 7 次坏 gold 的同族错误）；
若 gold 有但 top1 更像 → 才是检索问题或语料同质。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(1, '_synth'))
d = col.get(include=['documents', 'metadatas'])
metas = d['metadatas']
model = rag_service._get_model()

# 重建向量（绕开 include=['embeddings'] 的间歇失败）
texts = []
for doc, m in zip(d['documents'], metas):
    t, h = m.get('title', ''), m.get('heading', '')
    texts.append(f'{t}\n{h}\n{doc}' if t else f'{h}\n{doc}')
embs = np.asarray(model.encode(texts, normalize_embeddings=True,
                               show_progress_bar=False), dtype=np.float32)

# 笔记全文（把同 node 的块拼起来）
by_node = {}
for doc, m in zip(d['documents'], metas):
    by_node.setdefault(m['node_id'], []).append(doc)


def search(query, k=3):
    qv = np.asarray(rag_service.get_query_embedding(query), dtype=np.float32)
    order = np.argsort(np.linalg.norm(embs - qv[None, :], axis=1))
    seen, out = [], []
    for i in order:
        nid = metas[i]['node_id']
        if nid in seen:
            continue
        seen.append(nid)
        out.append((nid, float(1 - np.linalg.norm(embs[i] - qv) ** 2 / 2)))
        if len(out) >= k:
            break
    return out


CASES = [
    ('S02', 205, '判断一个元素一定不存在用什么结构'),
    ('S04', 208, '主从延迟导致读到旧数据怎么办'),
    ('S06', 212, '限流那几个算法怎么挑'),
    ('S07', 213, '怎么保证重复请求不会重复扣款'),
    ('S08', 220, '可观测性三个东西分别解决什么'),
    ('S13', 249, '这个月磁盘告警反复出现，根因是什么'),
    ('S14', 250, '问答笔记里怎么讲一致性哈希的'),
]

for cid, gold, q in CASES:
    hits = search(q)
    print('=' * 96)
    print(f'{cid}  query: {q}')
    print(f'  gold = node{gold}   检索结果: '
          f'{[(n, round(c, 3)) for n, c in hits]}')
    gtext = '\n'.join(by_node.get(gold, []))
    print(f'\n  --- GOLD node{gold} 原文（前 300 字）---')
    print('  ' + gtext[:300].replace('\n', '\n  '))
    t1 = hits[0][0]
    print(f'\n  --- 实际 top1 node{t1} 原文（前 300 字）---')
    print('  ' + '\n'.join(by_node.get(t1, []))[:300].replace('\n', '\n  '))
    # 关键判据：gold 里有没有 query 的核心词
    keys = [w for w in ('布隆', '比特', '副本', '从库', '令牌桶', '漏桶',
                        '唯一索引', '幂等', '指标', '日志', '追踪',
                        '磁盘', '归档', '一致性哈希', '虚拟节点') if w in q]
    if keys:
        present = [w for w in keys if w in gtext]
        print(f'\n  query 特征词 {keys} → 在 gold 里出现的: {present}')
    print()
