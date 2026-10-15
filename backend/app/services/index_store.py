"""统一索引连接；生产使用同一服务端索引，不回退到进程私有缓存。"""
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import chromadb


def parse_server_url(url: str) -> tuple[str, int, bool]:
    message = 'KB_CHROMA_URL must be an HTTP(S) origin without credentials or path'
    try:
        parsed = urlsplit(url)
        port = parsed.port
        host = parsed.hostname
        if (parsed.scheme not in {'http', 'https'} or not host or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or parsed.path not in {'', '/'} or any(char.isspace() for char in url)):
            raise ValueError(message)
        ssl = parsed.scheme == 'https'
        port = port if port is not None else (443 if ssl else 80)
        if not 1 <= port <= 65535:
            raise ValueError(message)
        # HTTP客户端构建URL时IPv6仍需方括号。
        return f'[{host}]' if ':' in host else host, port, ssl
    except (TypeError, ValueError):
        # 不把带密码/query token的原地址或第三方解析异常写到日志。
        raise ValueError(message) from None


def create_index_client(path: Path, *, url: str, production: bool) -> Any:
    if url:
        host, port, ssl = parse_server_url(url)
        return chromadb.HttpClient(host=host, port=port, ssl=ssl,
                                   settings=chromadb.Settings(anonymized_telemetry=False))
    if production:
        raise ValueError('KB_CHROMA_URL is required in production; local index is offline-only')
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(path=str(path), settings=chromadb.Settings(anonymized_telemetry=False))
