"""迁移前备份 chroma_db 目录（红线：任何不可逆操作前先留退路）。

做三件事：
1. 把整个 chroma_db 目录复制成带时间戳的副本（不删改原目录）
2. 打印每个集合的 count，作为"迁移前状态"的书面记录
3. 把这份记录写成 JSON，便于迁移后逐条对比

只读原目录 + 只写新目录，不触碰任何集合数据。
"""
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, r'C:/Users/陈独秀/knowledge-base/backend')
sys.stdout.reconfigure(encoding='utf-8')

BASE = Path(r'C:/Users/陈独秀/knowledge-base/backend')
SRC = BASE / 'chroma_db'
STAMP = datetime.now().strftime('%Y%m%d_%H%M%S')
DST = BASE / f'chroma_db_backup_{STAMP}'

if not SRC.exists():
    raise SystemExit(f'源目录不存在：{SRC}')

# 1) 复制
shutil.copytree(SRC, DST)
print(f'[备份] {SRC}')
print(f'    -> {DST}')

# 2) 记录各集合 count（只读）
from app.services import rag_service  # noqa: E402

collections = rag_service.chroma_client.list_collections()
state = {}
for c in collections:
    name = c.name if hasattr(c, 'name') else str(c)
    count = rag_service.chroma_client.get_collection(name=name).count()
    state[name] = count
    print(f'[集合] {name:<28} count = {count}')

# 3) 落盘
record = {
    'backup_dir': str(DST),
    'timestamp': STAMP,
    'kb_chroma_suffix': rag_service._SUFFIX,
    'collections': state,
}
out = DST / 'state_before_swap.json'
out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'[记录] {out}')
print(f'[当前生效后缀] KB_CHROMA_SUFFIX = {rag_service._SUFFIX!r}')
