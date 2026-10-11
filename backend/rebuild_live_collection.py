"""重建**线上**集合：`user_4_nodes`（无后缀）——修复 384 维残留导致的检索全面失效。

## 要修的到底是什么（2026-10-11 实测）
线上每一次知识库检索都在抛异常，被 `agent_tools.py:343-345` 的 `except Exception`
吞成 `{"error": "tool execution failed"}`，所以从用户视角只是"搜不到"，看不出是崩了：

    chromadb.errors.InvalidArgumentError: Collection expecting embedding with dimension of 384, got 1024

成因（git 可查）：
    aee1124 (初始)  SentenceTransformer('all-MiniLM-L6-v2')            → 384 维
    1297477 (09-10) 换成 BAAI/bge-large-zh-v1.5                        → 1024 维
                    commit message: "Recall@3 10.7% → 92.9%"
**换型时没有重新嵌入生产集合**，`user_4_nodes` 里留的是 MiniLM 时代的 384 维向量。
换型后的重建只覆盖了 `_prod` 影子集合（`build_prod_collection.py`），
而那个集合的 USER_ID 写死 1、真实笔记却属于 user 4 —— 见下方"为什么不复用现成脚本"。

## 为什么不能原地 upsert
实测：向 384 维集合 upsert 1024 维向量同样抛 InvalidArgumentError。
ChromaDB 集合的维度在建集合时锁定 ⇒ **必须删除集合再重建**。

## 为什么不复用 build_prod_collection.py（它有真 bug）
```python
USER_ID = 1
rows = db.query(KnowledgeNode).filter(KnowledgeNode.user_id == USER_ID).all()
if rows is None:      # ← 查不到数据返回的是 **空列表 []，不是 None**
    rows = load_from_sqlite()   # 于是静默回退到 2026-05-21 冻结 SQLite
```
真实笔记属于 user_id=4 ⇒ 该过滤条件返回 `[]` ⇒ **静默回退到冻结件**，
于是"生产集合"里装的是 12 条 05 月笔记，而不是 MySQL 里的 20 条。
本脚本因此**不复用它**，并把"空结果必须报错"写成硬约束。

## 安全设计
· 源 = MySQL（用户真实数据），**源为空直接 SystemExit，绝不回退**
· 目标 = `user_{LIVE_USER_ID}_nodes`（无后缀，线上生效集合）
· 只删该用户自己的集合，**不动任何其它集合**
· `--dry-run` 只打印将要做什么，不写库
· 写完回读校验：块数、维度、归一化模长、抽样自检
"""
import argparse
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap_live as B  # noqa: E402,F401  必须先于 app 导入（且它会断言无后缀）

sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models.node import KnowledgeNode  # noqa: E402
from app.services import rag_service  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--dry-run', action='store_true', help='只打印计划，不写库')
args = ap.parse_args()

print(B.describe())
print()

# ---- 1) 从 MySQL 读真实笔记（源为空 → 硬失败）----
db = SessionLocal()
try:
    nodes = (db.query(KnowledgeNode)
             .filter(KnowledgeNode.user_id == B.LIVE_USER_ID)
             .order_by(KnowledgeNode.id).all())
    rows = [(n.id, n.title or '', n.content or '') for n in nodes]
finally:
    db.close()

if not rows:
    # 这一条就是 build_prod_collection.py 的成因：空列表被当成"没问题"。
    raise SystemExit(
        f'[中止] user_id={B.LIVE_USER_ID} 在 MySQL 里没有任何笔记。\n'
        f'       绝不回退到其它数据源 —— 静默回退到冻结件正是本次故障的成因。'
    )
print(f'[源] MySQL user_id={B.LIVE_USER_ID}，{len(rows)} 条笔记: {[r[0] for r in rows]}')
empty = [r[0] for r in rows if not r[2].strip()]
if empty:
    print(f'⚠️ 内容为空的笔记: {empty}（会被跳过，无内容无法建向量）')
    rows = [r for r in rows if r[2].strip()]

# ---- 2) 目标集合 ----
col_name = rag_service.get_collection_name(B.LIVE_USER_ID)
col = rag_service.chroma_client.get_or_create_collection(name=col_name)
old_count = col.count()
print(f'[目标] {col_name}（当前 {old_count} 块）')

if args.dry_run:
    total = sum(len(rag_service.split_by_headings(c)) for _, _, c in rows)
    print(f'\n[dry-run] 将删除 {col_name} 并重建，预计 {total} 块：')
    for nid, title, content in rows:
        chunks = rag_service.split_by_headings(content)
        print(f'  node {nid:<3} {len(chunks):>2} 块  {title[:34]}')
    raise SystemExit(0)

# ---- 3) 删除并重建（维度锁定，不能原地 upsert）----
if old_count:
    existing = col.get()
    if existing['ids']:
        col.delete(ids=existing['ids'])
    print(f'[已清空] 删除 {len(existing["ids"])} 块')
rag_service.chroma_client.delete_collection(name=col_name)
col = rag_service.chroma_client.get_or_create_collection(name=col_name)
print(f'[新建] {col_name}（维度将按首次写入确定）')

total_chunks = 0
norm_bad = []
for nid, title, content in rows:
    chunks = rag_service.split_by_headings(content)
    ids, embs, docs, metas = [], [], [], []
    for i, (heading, chunk_content) in enumerate(chunks):
        # 与 add_node_to_index 完全同构：标题+小节标题拼进正文再编码
        embed_text = (f'{title}\n{heading}\n{chunk_content}' if title
                      else f'{heading}\n{chunk_content}')
        vec = np.asarray(rag_service.get_embedding(embed_text), dtype=np.float32)
        if abs(float(np.linalg.norm(vec)) - 1.0) > 0.01:
            norm_bad.append((nid, i, float(np.linalg.norm(vec))))
        ids.append(rag_service._chunk_id(nid, i))
        embs.append(vec.tolist())
        docs.append(chunk_content)
        metas.append({'title': title, 'node_id': nid, 'chunk_index': i, 'heading': heading})
    if ids:
        col.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
        total_chunks += len(ids)
    print(f'  node {nid:<3} {len(chunks):>2} 块  {title[:34]}')

# ---- 4) 回读校验 ----
print()
print(f'[完成] {len(rows)} 条笔记 → {total_chunks} 块；集合 count = {col.count()}')
d = col.get(include=['embeddings', 'metadatas'])
if d['embeddings'] is not None and len(d['embeddings']):
    dims = {len(e) for e in d['embeddings']}
    print(f'[维度校验] 集合内向量维度 = {dims}  ← 必须为 {{1024}}')
nids = sorted({m['node_id'] for m in d['metadatas']})
print(f'[覆盖校验] node = {nids}')
print(f'[归一化校验] 模长≠1.0 的块数 = {len(norm_bad)}  ← 必须为 0'
      + (f'  {norm_bad[:5]}' if norm_bad else ''))

# 真实检索冒烟：必须成功返回
print()
print('[冒烟] 重建后真实检索:')
for q in ('为什么要三次握手', '进程和线程的区别', '什么是 Linux 的 cgroup'):
    try:
        out = rag_service.retrieve_relevant_nodes(q, top_k=5, user_id=B.LIVE_USER_ID)
        tops = [(o['node_id'], (o.get('heading') or '')[:16]) for o in out[:3]]
        print(f'  ✓ {q}: {len(out)} 块，前3 = {tops}')
    except Exception as e:
        print(f'  ✗ {q}: {type(e).__name__}: {e}')
