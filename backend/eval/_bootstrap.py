"""评测脚本的公共引导：**必须在导入任何 app 模块之前 import 本模块**。

解决两个反复踩到的环境问题：

1. **数据库指向**：项目 `.env` 写的是 MySQL（本机 XAMPP 未启动），而评测的数据在
   旧 SQLite。`app/database.py` 在 **import 时**读 `settings.database_url`，
   所以必须在导入 app 之前把 `DATABASE_URL` 设成 SQLite。
   （与 `prepare_eval_corpus.py:14` 的做法一致；不在生产代码里加 DB 回退，
     因为生产就该用 MySQL。）

2. **NO_PROXY 畸形导致 httpx 崩溃**：本机 `NO_PROXY` 含 `[::1]`，httpx 会生成
   畸形模式 `all://*[::1]` → `InvalidURL: Invalid port: ':1]'`。
   必须在构造任何 httpx/OpenAI/anthropic 客户端之前净化。

用法（每个评测脚本的第一行导入）：
    import eval._bootstrap  # noqa: F401
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

# 1) sys.path：让 `from app...` 可用
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(BACKEND / 'eval') not in sys.path:
    sys.path.insert(0, str(BACKEND / 'eval'))

# 2) 数据库指向旧 SQLite（生产值来自 .env，此处仅为评测覆写）
_SQLITE = Path.home() / '.knowledge_base' / 'knowledge.db'
if _SQLITE.exists():
    os.environ['DATABASE_URL'] = f'sqlite:///{_SQLITE.as_posix()}'

# 3) 净化 NO_PROXY（必须在任何 http 客户端构造之前）
from app.env_sanitize import sanitize_no_proxy  # noqa: E402

sanitize_no_proxy()

# 4) 生产集合后缀（评测要测线上那一份）
os.environ.setdefault('KB_CHROMA_SUFFIX', '_prod')
