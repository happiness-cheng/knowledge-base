"""定位：哪个集合在 include=['embeddings'] 时读不出来。

背景：`bench_v2.py` 里 `col.get(include=['embeddings','metadatas'])` 抛
`Error creating hnsw segment reader: Nothing found on disk`，
但同一批集合的 `count()` 与 `get(include=[])`（只读 metadata）都正常。
⇒ 问题在"读向量"这条路径上，需要逐集合定位，并检查向量文件是否真的在盘上。
"""
import sys
from pathlib import Path

_BACKEND = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(_BACKEND))
sys.path.insert(0, str(_BACKEND / 'eval'))
import _bootstrap  # noqa: E402,F401

sys.stdout.reconfigure(encoding='utf-8')

from app.services import rag_service  # noqa: E402

FORMS = [
    ('只 ids', ['']),
    ('ids+metadatas', ['metadatas']),
    ('ids+documents', ['documents']),
    ('ids+embeddings', ['embeddings']),
]

for col in rag_service.chroma_client.list_collections():
    name = col.name
    handle = rag_service.chroma_client.get_collection(name=name)
    try:
        n = handle.count()
    except Exception as e:
        print(f'{name:<22} count 就失败: {type(e).__name__}')
        continue
    line = f'{name:<22} count={n:<5}'
    for label, inc in FORMS:
        try:
            kw = {'include': inc} if inc != [''] else {}
            handle.get(**kw)
            line += f' {label}=OK'
        except Exception as e:
            line += f' {label}=FAIL({type(e).__name__}: {str(e)[:38]})'
    print(line)

# 盘上文件检查：向量在 HNSW 的 .bin 里
print('\n=== 集合目录的 .bin 文件（有 data_level0.bin 才说明向量在盘上）===')
chroma = _BACKEND / 'chroma_db'
import sqlite3  # noqa: E402
con = sqlite3.connect(f'file:{chroma / "chroma.sqlite3"}?mode=ro', uri=True)
seg2col = {}
for seg_id, col_id in con.execute(
        "SELECT id, collection FROM segments WHERE scope='VECTOR'"):
    seg2col[seg_id] = col_id
name_of = {cid: nm for cid, nm in con.execute('SELECT id, name FROM collections')}
con.close()
for seg_id, col_id in seg2col.items():
    d = chroma / seg_id
    bins = sorted(d.glob('*.bin')) if d.is_dir() else []
    info = ', '.join(f'{b.name}={b.stat().st_size}' for b in bins) or '无 .bin'
    print(f'  {name_of.get(col_id, col_id):<22} {info}')
