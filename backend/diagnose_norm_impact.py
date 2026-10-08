"""量化"归一化不一致"的危害 + 验证修复方案（只读，不写库）。

背景：
  rag_service.get_embedding() → model.encode(text)              ← 无归一化，norm≈18.1
  eval/run_kb_eval.py:130,136 → encode(..., normalize_embeddings=True)  ← 归一化，norm=1.0

后果推断：生产检索的"距离"与评测的"余弦"不是同一量纲；且库里两种量纲的向量混存。
本脚本量出：
  1. 库里各类向量的 norm 分布（找出有多少条是"另一套量纲"）
  2. 同一 query，归一化前/后的 top-3 排名是否变化（= 归一化到底影响多大）
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

col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(USER, ""))
data = col.get(include=['embeddings', 'metadatas'])
embs = np.asarray(data['embeddings'], dtype=np.float32)
norms = np.linalg.norm(embs, axis=1)

print(f'[集合] {col.name}  共 {len(norms)} 条向量，dim={embs.shape[1]}')
print(f'  norm 分布: min={norms.min():.3f} max={norms.max():.3f} 均值={norms.mean():.3f}')
near1 = int((np.abs(norms - 1.0) < 0.01).sum())
print(f'  norm≈1（已归一化）的条数 = {near1}')
print(f'  norm≈1 之外的条数        = {len(norms) - near1}  ← 两套量纲混存')
sample = [(data['ids'][i], round(float(norms[i]), 3)) for i in range(min(6, len(norms)))]
print(f'  样例 id→norm: {sample}')

# --- 归一化前 vs 后，排名是否变化 ---
model = rag_service._get_model()


def topk(qvec, k=3):
    q = np.asarray(qvec, dtype=np.float32)
    d = np.linalg.norm(embs - q[None, :], axis=1)
    idx = np.argsort(d)[:k]
    return [(data['ids'][i], round(float(d[i]), 4)) for i in idx]


raw_q = model.encode(rag_service.QUERY_PREFIX + Q)                 # 不归一化
norm_q = model.encode(rag_service.QUERY_PREFIX + Q, normalize_embeddings=True)

print(f'\n[未归一化查询] norm={np.linalg.norm(raw_q):.3f}')
for i, (id_, d) in enumerate(topk(raw_q), 1):
    print(f'  #{i} {id_:>6}  L2²={d}')
print(f'[已归一化查询] norm={np.linalg.norm(norm_q):.3f}')
for i, (id_, d) in enumerate(topk(norm_q), 1):
    print(f'  #{i} {id_:>6}  L2²={d}')

ids_raw = [i for i, _ in topk(raw_q, 10)]
ids_norm = [i for i, _ in topk(norm_q, 10)]
print(f'\n[对比] top-10 完全一致? {ids_raw == ids_norm}')
print(f'  未归一化 top-10: {ids_raw}')
print(f'  已归一化 top-10: {ids_norm}')

# --- 只对"已归一化"的那部分做对照（排除混存干扰） ---
mask = np.abs(norms - 1.0) < 0.01
if mask.sum() >= 3:
    sub = embs[mask]
    sub_ids = [data['ids'][i] for i in range(len(norms)) if mask[i]]

    def topk_sub(qvec, k=3):
        q = np.asarray(qvec, dtype=np.float32)
        d = np.linalg.norm(sub - q[None, :], axis=1)
        idx = np.argsort(d)[:k]
        return [(sub_ids[i], round(float(d[i]), 4)) for i in idx]

    print(f'\n[仅 norm≈1 子集，{mask.sum()} 条]')
    print('  未归一化查询:', topk_sub(raw_q))
    print('  已归一化查询:', topk_sub(norm_q))
