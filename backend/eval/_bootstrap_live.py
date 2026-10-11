"""评测引导（**真实在线链路**版）：MySQL + user_4 + user_4_nodes（无后缀）。

## 为什么必须有这个文件（2026-10-11 实测，一次严重的评测-生产错位）
原 `_bootstrap.py` 有三处硬编码，导致评测跑在与线上**完全不同**的数据上，
而我自己没发现，还在这套数据上报了 44/44、0.977、0.970：

| 位置 | 原值 | 后果 |
|---|---|---|
| `_bootstrap.py:35` | `DATABASE_URL` → 05-21 冻结 SQLite | MySQL 里 20 个 node，SQLite 只有 12 个 |
| `_bootstrap.py:43` | `KB_CHROMA_SUFFIX=_prod` | 查 `user_1_nodes_prod`（eval 专用影子集合） |
| `eval_set_v3.py:211` | `KnowledgeNode.user_id == 1` | 真实笔记属于 **user_id=4**（user 1 有 0 条） |

实测证据（同一台机器）：
    MySQL : user_id=1 → 0 条; user_id=3 → 1 条; user_id=4 → 20 条
    SQLite: 12 条 ids=[1,2,3,5,7,8,12,13,14,16,17,18]
    user_1_nodes_prod 的 node_id = [1,2,3,5,7,8,12,13,14,16,17,18]  ← 与 SQLite 完全一致
    user_4_nodes      的 node_id = [1,...,28] 共 20 个              ← 与 MySQL user 4 完全一致
⇒ 线上链路是 **MySQL + user_4 + user_4_nodes**（`.env` 里的 `KB_CHROMA_SUFFIX`
  经 `app/env_sanitize.py` 核对**不在提升白名单**，所以后端不带后缀），
  而评测跑的是 SQLite + user_1 + user_1_nodes_prod。**两者毫无交集。**

## 用法
    import _bootstrap_live as B   # 必须在导入任何 app 模块之前
    print(B.describe())
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
if str(BACKEND / 'eval') not in sys.path:
    sys.path.insert(0, str(BACKEND / 'eval'))

# ---- 1) 数据库：用 .env 的 MySQL（线上真源），不覆写成 SQLite ----
# 刻意**不设** DATABASE_URL：让 app.config 读 .env。
# 如果 .env 缺失或 MySQL 未启动，会在 import app.database 时立刻失败 —— 这是想要的行为，
# 因为"静默回退到冻结件"正是本次错位的成因。
_here = Path(__file__).resolve().parent
_dotenv = BACKEND / '.env'
# ⚠️ `.env` 里写着 `KB_CHROMA_SUFFIX=_prod`，但那个值**对线上不生效**
# （不在 `app/env_sanitize.ENV_KEYS_TO_PROMOTE` 提升白名单里，且 `.env` 早于此模块导入）。
# 实测踩坑：先前这里把 `.env` 全量 setdefault 进 os.environ，于是 `_prod` 被带进来，
# rag_service 的模块级 `_SUFFIX` 读到了它 ⇒ 又查到了空集合 `user_4_nodes_prod`（0 块），
# 44 条用例全部 0/44。**必须先排除这个键**，再谈"数据源对了"。
_SKIP_KEYS = {'KB_CHROMA_SUFFIX'}
if _dotenv.exists():
    for _line in _dotenv.read_text(encoding='utf-8').splitlines():
        _line = _line.strip()
        if _line and not _line.startswith('#') and '=' in _line:
            _k, _v = _line.split('=', 1)
            if _k.strip() in _SKIP_KEYS:
                continue
            os.environ.setdefault(_k.strip(), _v.strip())

# ---- 2) 集合后缀：线上无后缀（见文件头实测）----
# 注意：真正生效的清除在**第 4 步之后**（env_sanitize 会把 _prod 写回来），
# 这里只做一次前置清理，避免任何早于 env_sanitize 的读取拿到 _prod。
os.environ.pop('KB_CHROMA_SUFFIX', None)

# ---- 3) 真实用户 ----
# 笔记全部属于 user_id=4（user 1 有 0 条）。任何按 user_id=1 的查询都会静默返回空。
LIVE_USER_ID = 4

# ---- 4) 净化 NO_PROXY（必须在构造任何 http 客户端之前）----
# ⚠️ 导入 `app.env_sanitize` 的**副作用**：它模块末尾第 75 行会调用 `load_dotenv_keys()`，
# 把 `.env` 里的 `KB_CHROMA_SUFFIX=_prod` 提升进 `os.environ`
# （见 `ENV_KEYS_TO_PROMOTE`）。实测踩坑：先 pop 再导入，等于白 pop ——
# 环境变量被它重新写回 `_prod`，于是又查到空集合 `user_4_nodes_prod`（0 块），
# 44 条用例全部 0/44（我就是这样连续踩了两次）。
# 所以**必须在导入 env_sanitize 之后**再清除。
from app.env_sanitize import sanitize_no_proxy  # noqa: E402

sanitize_no_proxy()
os.environ.pop('KB_CHROMA_SUFFIX', None)


def _assert_live_suffix() -> None:
    """回读校验：确认 rag_service 真的用了无后缀集合。

    为什么要有这道断言：本次错位的本质就是"配置看起来生效了其实没生效"。
    `rag_service._SUFFIX` 在**模块导入时**读一次 `os.environ`，所以任何早于
    `import rag_service` 的环境变量写入都会决定它 —— 静默失败的方式太多，
    唯一可靠的做法是导入后**回读并断言**。
    """
    from app.services import rag_service
    if rag_service._SUFFIX != '':
        raise RuntimeError(
            f'评测数据源校验失败：rag_service._SUFFIX = {rag_service._SUFFIX!r}，'
            f'期望 ""（无后缀=线上集合）。检查是否有 .env/环境变量把 KB_CHROMA_SUFFIX '
            f'又设回去了。实际会查到 {rag_service.get_collection_name(LIVE_USER_ID)}。'
        )


_assert_live_suffix()


def describe() -> str:
    """打印本次评测实际连的数据源，避免"以为在测线上"。"""
    from app.database import engine
    from app.services import rag_service
    col = rag_service._get_user_collection(LIVE_USER_ID)
    return (f'[评测数据源] DB={engine.url}\n'
            f'             集合={col.name}（{col.count()} 块）\n'
            f'             user_id={LIVE_USER_ID}\n'
            f'             KB_CHROMA_SUFFIX={os.environ.get("KB_CHROMA_SUFFIX")!r}（None=无后缀=线上）')
