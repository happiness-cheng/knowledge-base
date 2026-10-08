"""制造并复现"量纲不一致"故障（E3 式实验）。

做法（可完全回滚）：
  1. 先跑一次正常检索，记录 top-3
  2. 往 user_1_nodes 里 upsert **一条只有量纲不同**的向量：
     取库里某条真实向量，乘 18.13（模拟 get_embedding 不归一化的产物）
     —— 语义内容完全相同，只有模长不同
  3. 再跑同一 query：看这条"同语义、异模长"的记录是否**霸榜**
  4. 删除该条，复跑，确认恢复到第 1 步结果

为什么这条实验值得做：它证明"归一化"不是代码风格问题，而是**能不能检索到**的问题。
"""
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

USER = 1
Q = "为什么需要堆内存，栈空间默认多大"
TEST_ID = "zz_test_unnormalized"

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(USER, ""))


def probe(tag):
    res = rag_service.retrieve_relevant_nodes(Q, top_k=3, user_id=USER)
    print(f'  [{tag}]')
    for rank, r in enumerate(res, 1):
        print(f'    #{rank} node={r["node_id"]:>5} chunk={r.get("chunk_index")} '
              f'dist={r["distance"]:.4f} title={r.get("title", "")[:22]!r}')
    return [r['node_id'] for r in res]


print('=' * 66)
print('步骤1  正常检索（基线）')
before = probe('基线')

# 取库里一条真实向量（用实际存在的 id，不硬编码；旧集合 id 是 '3' 这种格式）
all_ids = col.get(include=[])['ids']
donor_id = next((i for i in all_ids if ':' not in str(i) and str(i).lstrip('-').isdigit()
                 and not str(i).startswith('-')), all_ids[0])
donor = col.get(ids=[donor_id], include=['embeddings', 'documents', 'metadatas'])
donor_vec = np.asarray(donor['embeddings'][0], dtype=np.float32)
SCALE = 18.13
scaled = (donor_vec * SCALE).tolist()
print(f'\n步骤2  写入 1 条"同语义、模长 x{SCALE}"的向量')
print(f'       源 id={donor_id}  norm={np.linalg.norm(donor_vec):.3f} → '
      f'新 norm={np.linalg.norm(np.asarray(scaled)):.3f}')
col.upsert(
    ids=[TEST_ID],
    embeddings=[scaled],
    documents=donor['documents'],
    metadatas=[{**donor['metadatas'][0], 'test': True}],
)
print(f'       集合 count = {col.count()}')

print('\n步骤3  同一 query 复跑 —— 观察是否霸榜')
after = probe('写入后')

print('\n步骤4  清理并复核')
col.delete(ids=[TEST_ID])
print(f'       已删除 {TEST_ID}；集合 count = {col.count()}')
restored = probe('清理后')

print('\n' + '=' * 66)
print(f'基线 top-3     : {before}')
print(f'写入后 top-3   : {after}')
print(f'清理后 top-3   : {restored}')
print(f'是否被霸榜     : {"是 ❌ 归一化是检索正确性的必要条件" if after != before else "否"}')
print(f'是否已恢复原状 : {"是 ✅" if restored == before else "否 ❌"}')
