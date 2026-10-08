"""定位"距离异常"：直接量向量，不猜。

假设清单（逐个证伪）：
  H1 查询向量维度与集合不匹配（384 vs 1024）
  H2 查询向量未归一化（numpy 默认路径不归一化，torch 路径才归一化）
  H3 check_state.py 与 retrieve_relevant_nodes 走的不是同一套查询
"""
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

Q = "为什么需要堆内存，栈空间默认多大"

# --- H1/H2: 查询向量本身 ---
model = rag_service._get_model()
print(f'[模型] {model.__class__.__name__}')
print(f'  max_seq_length = {model.max_seq_length}')

qv = np.asarray(rag_service.get_query_embedding(Q), dtype=np.float32)
print(f'\n[查询向量] dim={qv.shape[0]}  dtype={qv.dtype}')
print(f'  L2 范数 = {np.linalg.norm(qv):.6f}   ← 1.0 才表示已归一化')
print(f'  均值={qv.mean():.6f}  std={qv.std():.6f}')

# get_embedding 对普通文本（无前缀）的表现
dv = np.asarray(rag_service.get_embedding("虚拟内存"), dtype=np.float32)
print(f'[文档向量] dim={dv.shape[0]}  L2 范数 = {np.linalg.norm(dv):.6f}')

# encode 的默认行为（不传 normalize_embeddings）
raw = model.encode("测试文本")
print(f'\n[encode 默认] dim={raw.shape[0]}  L2 范数 = {np.linalg.norm(raw):.6f}')
norm = model.encode("测试文本", normalize_embeddings=True)
print(f'[encode 归一化] dim={norm.shape[0]}  L2 范数 = {np.linalg.norm(norm):.6f}')

# --- H3: 两种查询路径对比 ---
col = rag_service.chroma_client.get_collection(name="user_1_nodes")

print('\n[路径A] collection.query（check_state.py 的写法）')
res = col.query(query_embeddings=[qv.tolist()], n_results=3)
for i in range(3):
    print(f'  {res["ids"][0][i]:>6}  dist={res["distances"][0][i]:.6f}')

print('\n[路径B] retrieve_relevant_nodes（生产读路径）')
for r in rag_service.retrieve_relevant_nodes(Q, top_k=3, user_id=1):
    print(f'  {r["node_id"]:>6}  dist={r["distance"]:.6f}')

# --- 直接查库里的向量本身长什么样（绕开所有代码） ---
print('\n[库里存储向量] 直接看 3 条')
raw_data = col.get(ids=[res['ids'][0][0]], include=['embeddings'])
emb = np.asarray(raw_data['embeddings'][0], dtype=np.float32)
print(f'  id={res["ids"][0][0]}  dim={emb.shape[0]}  L2范数={np.linalg.norm(emb):.6f}')
