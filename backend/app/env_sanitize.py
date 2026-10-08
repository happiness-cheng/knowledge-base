"""进程环境净化：在**任何**库读取环境变量之前调用。

为什么必须有这个模块（2026-10-07 本机实测，两次真实崩溃）：
  环境变量 NO_PROXY = "localhost,127.0.0.1,::1,[::1]"（带方括号的 IPv6）
  httpx 会为每个条目生成 `all://{host}` 和 `all://*{host}` 两个模式，
  带括号的 [::1] 被**再包一次** → 畸形模式 `all://*[::1]` → URLPattern 解析出 ':1]'
  → httpx.InvalidURL: Invalid port: ':1]'

受害点（都是"库在 import 期自建 httpx client"）：
  1. anthropic.Anthropic()（trust_env=True）→ claude_client 模块导入即崩 → 整个后端起不来
  2. huggingface_hub 的全局 client → 模型加载（SentenceTransformer）时崩

  而 httpx 只在 **Client 构造时** 读环境变量 ⇒ 只要在**导入任何这些库之前**修好
  环境变量，两个受害点就同时消失。反过来，任何"事后才设"（例如在 _get_model()
  里设 HF_HUB_OFFLINE）都太晚——huggingface_hub 在 import 期已把常量缓存走了。

为什么不直接传 trust_env=False：那会连带忽略用户**有意配置**的 HTTP_PROXY/HTTPS_PROXY，
公司网络下所有外呼都会失败。这里只修真正畸形的那部分，保留代理能力。
"""
import os
from pathlib import Path

# 必须在导入 transformers / sentence_transformers / huggingface_hub 之前生效
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

# 需要从 .env 提升到 os.environ 的键
ENV_KEYS_TO_PROMOTE = ("KB_CHROMA_SUFFIX",)


def load_dotenv_keys(keys: tuple[str, ...] = ENV_KEYS_TO_PROMOTE) -> dict[str, str]:
    """把 .env 里指定的键写进 os.environ（已存在的环境变量优先，不覆盖）。

    为什么需要这一层（真实踩坑）：
      在 backend/.env 写了 `KB_CHROMA_SUFFIX=_prod` 本以为生效，但 app/config.py 用的是
      pydantic-settings，它只把 .env 的值放进 Settings **对象**，不会写进 os.environ；
      而 rag_service 直接读 os.environ ⇒ 读到空值 ⇒ **静默继续用旧集合**。
      "配置看起来生效了其实没生效"比报错危险得多，所以配套要有回读验证脚本
      （verify_effective_config.py）。
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return {}
    applied: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key in keys and key not in os.environ:
            os.environ[key] = value
            applied[key] = value
    return applied


def sanitize_no_proxy() -> list[str]:
    """去掉 NO_PROXY 条目里的方括号。返回被改动的变量名（便于日志）。"""
    changed = []
    for name in ("NO_PROXY", "no_proxy"):
        value = os.environ.get(name)
        if not value:
            continue
        fixed = ",".join(
            part.strip().strip("[]") if part.strip().startswith("[") else part.strip()
            for part in value.split(",")
        )
        if fixed != value:
            os.environ[name] = fixed
            changed.append(name)
    return changed


sanitize_no_proxy()
load_dotenv_keys()
