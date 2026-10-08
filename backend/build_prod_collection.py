"""重建"生产集合"：从**真实笔记库**读取内容，走生产切分器写向量。

与 rebuild_user1.py 的区别（这是本脚本存在的全部理由）：

| | rebuild_user1.py | 本脚本 |
|---|---|---|
| 数据源 | eval/corpus_*.json（**评测语料**） | 真实笔记库（MySQL 或 SQLite） |
| 数据源性质 | 可再生成，但不是真值 | 真实笔记 |
| 后果 | 把评测数据灌进生产集合，真实笔记被挤出 | 生产集合只含真实笔记 |
| 回滚 | `col.delete(所有)` 后无源可恢复 → **不可回滚** | 旧集合原样留存 → 删环境变量即回退 |

⚠️ 数据源现状（2026-10-07 实测，必须如实记录）：
  · `.env` 写的是 MySQL（`mysql+pymysql://root:@127.0.0.1:3306/knowledge_base`）
  · 但本机 MySQL（XAMPP，`D:\\xampp\\mysql`）**服务从未启动**，3306 无监听，
    `D:\\xampp\\mysql\\data\\knowledge_base\\*.ibd` 最后写入 2026-05-26
  · 旧 SQLite `~/.knowledge_base/knowledge.db` 最后写入 2026-05-21，两者都是 5 月冻结件
  · tracker 已实测：两边 12 条笔记内容一致
  ⇒ 因此本脚本**优先 MySQL，连不上则回退 SQLite 并显著告警**，
    并在输出里标明本次数据源，避免"以为自己在读生产库"。

安全设计：
- 只写 suffix 指定的集合（默认 "_prod"），**永不触碰** user_1_nodes
- 幂等：先清空目标集合再写，可重复运行
- 逐 node upsert：某个 node 失败不影响其他 node
- 写完打印每条笔记的向量模长，确认全部 = 1.0（归一化回归）
"""
import sqlite3
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import numpy as np  # noqa: E402
from app.services import rag_service  # noqa: E402

USER_ID = 1
PROD_SUFFIX = "_prod"
SQLITE_PATH = Path.home() / '.knowledge_base' / 'knowledge.db'


def load_from_mysql():
    """真·生产数据源。连不上返回 None 并说明原因。"""
    try:
        from app.database import SessionLocal
        from app.models.node import KnowledgeNode
        db = SessionLocal()
        try:
            db.get_bind().connect()          # 立刻探活，别等到 query 才炸
            rows = (db.query(KnowledgeNode)
                    .filter(KnowledgeNode.user_id == USER_ID)
                    .order_by(KnowledgeNode.id).all())
            return [(n.id, n.title or '', n.content or '') for n in rows]
        finally:
            db.close()
    except Exception as e:
        print(f'[MySQL 不可用] {type(e).__name__}: {str(e)[:120]}')
        return None


def load_from_sqlite():
    if not SQLITE_PATH.exists():
        raise SystemExit(f'SQLite 也不存在：{SQLITE_PATH}')
    con = sqlite3.connect(f'file:{SQLITE_PATH}?mode=ro', uri=True)
    try:
        return [(r[0], r[1] or '', r[2] or '') for r in
                con.execute('SELECT id, title, content FROM knowledge_nodes ORDER BY id')]
    finally:
        con.close()


rows = load_from_mysql()
if rows is None:
    print('[⚠️ 回退数据源] 改用旧 SQLite —— 其中内容为 2026-05 冻结件，')
    print('              与 MySQL 的一致性由 tracker 记录保证，非本次实测。')
    print(f'              路径: {SQLITE_PATH}')
    rows = load_from_sqlite()
    source = f'SQLite({SQLITE_PATH.name})'
else:
    source = 'MySQL(knowledge_base)'

print(f'[数据源] {source}')
print(f'[真实笔记] {len(rows)} 条: id={[r[0] for r in rows]}')

col = rag_service.chroma_client.get_or_create_collection(
    name=rag_service.get_collection_name(USER_ID, PROD_SUFFIX))
print(f'[目标集合] {col.name}（写前 count = {col.count()}）')

existing = col.get()
if existing['ids']:
    col.delete(ids=existing['ids'])

total_chunks = 0
norm_bad = 0
for nid, title, content in rows:
    chunks = rag_service.split_by_headings(content)
    ids, embs, docs, metas = [], [], [], []
    for i, (heading, chunk_content) in enumerate(chunks):
        embed_text = (f"{title}\n{heading}\n{chunk_content}" if title
                      else f"{heading}\n{chunk_content}")
        vec = np.asarray(rag_service.get_embedding(embed_text), dtype=np.float32)
        if abs(float(np.linalg.norm(vec)) - 1.0) > 0.01:
            norm_bad += 1
        ids.append(rag_service._chunk_id(nid, i))
        embs.append(vec.tolist())
        docs.append(chunk_content)
        metas.append({"title": title, "node_id": nid, "chunk_index": i, "heading": heading})
    if ids:
        col.upsert(ids=ids, embeddings=embs, documents=docs, metadatas=metas)
        total_chunks += len(ids)
    print(f'  node {nid:<3} {len(chunks):>2} 块  title={title[:24]!r}')

print(f'[完成] {len(rows)} 条笔记 → {total_chunks} 块；count = {col.count()}')
print(f'[归一化检查] 模长≠1.0 的向量数 = {norm_bad}  ← 必须为 0')

