"""零写入地证明："库内模长不一致 → 排名崩坏"，并验证修复方案。

不往库里写任何东西。直接用 user_1_nodes 的 299 条向量做三组对照：
  A) 全部归一化（现状：库里数据 + 假设查询也归一化）
  B) 全部不归一化（假设历史数据也是 get_embedding 产的，一致但非单位模长）
  C) **混合**：老数据 norm=1，新写入 norm≈18（当前代码一旦有写入就会变成这样）

判据：三组对同一批 query 的 top-10 是否一致。C 与 A 差异越大，说明"混存"越危险。
"""
import json
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

USER = 1
col = rag_service.chroma_client.get_collection(
    name=rag_service.get_collection_name(USER, ""))
data = col.get(include=['embeddings', 'metadatas'])
ids = data['ids']
V = np.asarray(data['embeddings'], dtype=np.float32)      # 299 x 1024，norm=1

model = rag_service._get_model()

# 复用评测集里已经写好的 28 条 query（避免我手写 query 违反"零重词"纪律）
cases = json.loads((BASE / 'eval/kb_eval_expanded_bge_final.json')
                   .read_text(encoding='utf-8'))
queries = []
# 评测 json 只存了结果，不存 query 文本 ⇒ 从 run_kb_eval.py 的 CASES 里取
import importlib.util  # noqa: E402
spec = importlib.util.spec_from_file_location('rke', BASE / 'eval/run_kb_eval.py')
rke = importlib.util.module_from_spec(spec)
sys.modules['rke'] = rke
spec.loader.exec_module(rke)          # 只加载 CASES，不执行 __main__
queries = [c['query'] for c in rke.CASES]
print(f'[query 来源] eval/run_kb_eval.py 的 CASES，共 {len(queries)} 条')


def rank_top10(Vdoc, qvec):
    d = np.linalg.norm(Vdoc - qvec[None, :], axis=1)
    return [ids[i] for i in np.argsort(d)[:10]]


# 查询向量：模拟"生产 get_embedding"（不归一化）
Q_raw = np.asarray(model.encode([rag_service.QUERY_PREFIX + q for q in queries]),
                   dtype=np.float32)
# 归一化版
Q_norm = Q_raw / np.linalg.norm(Q_raw, axis=1, keepdims=True)

# 文档池三种状态
V_norm = V                                                    # A: 已归一化
V_raw = V * 18.13                                             # B: 全部同倍放大
V_mixed = V.copy()
V_mixed[::2] = V_mixed[::2] * 18.13                           # C: 一半老一半新

print(f'\n各方案的向量模长:')
print(f'  A 原文库      : {np.linalg.norm(V_norm, axis=1).min():.2f} ~ '
      f'{np.linalg.norm(V_norm, axis=1).max():.2f}')
print(f'  B 全部放大    : {np.linalg.norm(V_raw, axis=1).min():.2f} ~ '
      f'{np.linalg.norm(V_raw, axis=1).max():.2f}')
print(f'  C 混合(一半)  : {np.linalg.norm(V_mixed, axis=1).min():.2f} ~ '
      f'{np.linalg.norm(V_mixed, axis=1).max():.2f}')

results = {}
for name, Vd, Qv in [
    ('A 归一化数据 + 归一化查询', V_norm, Q_norm),
    ('B 未归一化数据 + 未归一化查询', V_raw, Q_raw),
    ('C 混存数据 + 未归一化查询', V_mixed, Q_raw),
]:
    results[name] = [rank_top10(Vd, Qv[i]) for i in range(len(queries))]

base = results['A 归一化数据 + 归一化查询']


def agreement(other):
    same = sum(1 for a, b in zip(base, other) if a == b)
    # 逐位置重合率
    pos = sum(len(set(a) & set(b)) for a, b in zip(base, other)) / (10 * len(base))
    return same, pos


print(f'\n与 A 对照（{len(queries)} 条 query）:')
for name, r in results.items():
    if name.startswith('A'):
        continue
    same, pos = agreement(r)
    print(f'  {name:<34} top-10 完全一致 {same}/{len(queries)} 条；'
          f'逐位置重合率 {pos * 100:.1f}%')

# 给出一个具体例子，便于肉眼确认
i = 0
print(f'\n示例 query: {queries[i][:40]}...')
for name, r in results.items():
    print(f'  {name}')
    print(f'    {r[i][:6]}')
