"""逐个集合探活：哪个集合的索引能读、哪个读不了。

背景：backup_chroma_now.py 在遍历集合 count() 时抛
  chromadb.errors.InternalError: Error loading hnsw index
说明至少有一个集合的 HNSW 段损坏（或 chroma 版本与数据格式不匹配）。
本脚本逐个 try/except，**先定位是哪个集合**，不改任何数据。
"""
import sys
from pathlib import Path

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
sys.path.insert(0, str(BASE))
sys.stdout.reconfigure(encoding='utf-8')

import chromadb  # noqa: E402

client = chromadb.PersistentClient(path=str(BASE / 'chroma_db'))
cols = client.list_collections()
print(f'共 {len(cols)} 个集合\n')

for c in cols:
    name = c.name
    # get_collection 只拿句柄不读索引；count() / get() 才会触发索引加载
    try:
        handle = client.get_collection(name=name)
        count = handle.count()
        print(f'[OK]   {name:<28} count = {count}')
    except Exception as e:
        print(f'[FAIL] {name:<28} {type(e).__name__}: {str(e)[:110]}')
    try:
        handle = client.get_collection(name=name)
        n_meta = len(handle.get(include=[])['ids'])
        print(f'       └ metadata 可读: {n_meta} 条 id')
    except Exception as e:
        print(f'       └ metadata 也读不了: {type(e).__name__}: {str(e)[:80]}')
