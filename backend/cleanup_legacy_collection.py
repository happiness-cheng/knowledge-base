"""处置损坏的遗留集合 `knowledge_nodes`（旧 MiniLM 384 维，HNSW 索引已损坏）。

结论依据（2026-10-07 实测，只读探查）：
  · 38 条记录的 title 全是测试数据：`Node 3`/`Node B`/`RA`/`RB`/
    `格式测试_H2格式_R1`/`Playwright自动化测试节点` 等
  · HNSW 索引文件不存在（集合目录仅 1000 字节 header，无 data_level0.bin）
    ⇒ 向量已不可恢复（ChromaDB 1.5.9 向量不存 sqlite，只在 .bin 里）
  · 生产代码对它的引用数 = 0（grep 命中的 `knowledge_nodes` 全是 SQL 表名）
  · 保住也无用：查它会抛 InternalError，不能读、不能检索

本脚本动作（可回退）：
  1. 把该集合的 38 条 id/title/正文**导出成 JSON**（正文还有价值，向量没有）
  2. 尝试删除该集合
  3. 删除后复核：生产集合不受影响（count 不变）
"""
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import chromadb  # noqa: E402

TARGET = 'knowledge_nodes'
client = chromadb.PersistentClient(path=str(BASE / 'chroma_db'))

# --- 1) 导出可救的部分（元数据 + 正文；向量已丢）---
con_path = BASE / 'chroma_db' / 'chroma.sqlite3'
import sqlite3  # noqa: E402
con = sqlite3.connect(f'file:{con_path}?mode=ro', uri=True)
rows = con.execute('''
SELECT e.embedding_id, em.key, em.string_value
FROM embedding_metadata em
JOIN embeddings e ON em.id = e.id
JOIN segments s ON e.segment_id = s.id
JOIN collections c ON s.collection = c.id
WHERE c.name = ?
''', (TARGET,)).fetchall()
con.close()

docs: dict[str, dict] = {}
for eid, key, value in rows:
    docs.setdefault(eid, {'embedding_id': eid})[key] = value

stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
out = BASE / f'legacy_knowledge_nodes_export_{stamp}.json'
out.write_text(json.dumps(list(docs.values()), ensure_ascii=False, indent=2),
               encoding='utf-8')
print(f'[导出] {len(docs)} 条记录 → {out.name}')
print(f'       样例 title: {[d.get("title") for d in list(docs.values())[:6]]}')

# --- 2) 删除集合 ---
before = {c.name: c for c in client.list_collections()}
print(f'\n[删除前] 集合清单: {sorted(before)}')
try:
    client.delete_collection(TARGET)
    print(f'[删除] {TARGET} 已删除')
except Exception as e:
    print(f'[删除失败] {type(e).__name__}: {e}')
    raise SystemExit(1)

# --- 3) 复核 ---
after = {c.name: c for c in client.list_collections()}
print(f'[删除后] 集合清单: {sorted(after)}')

print('\n[复核] 其余集合 count（应全部不变）:')
expect = {
    'user_1_nodes': 299,
    'user_1_nodes_prod': 57,
    'user_1_nodes_eval': 299,
}
ok = True
for name, want in expect.items():
    if name not in after:
        print(f'  ❌ {name} 不见了！')
        ok = False
        continue
    got = client.get_collection(name).count()
    flag = '✅' if got == want else '❌'
    if got != want:
        ok = False
    print(f'  {flag} {name:<20} count={got}（期望 {want}）')
print(f'\n总体：{"✅ 遗留集合已清除，其余集合零影响" if ok else "❌ 有异常，需人工检查"}')
