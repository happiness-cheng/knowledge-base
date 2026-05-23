import os
import sys
import json
from pydantic_settings import BaseSettings


def _get_env_file():
    if getattr(sys, "frozen", False):
        return None
    return os.environ.get("ENV_FILE", ".env")


def _resolve_paths():
    base_dir = os.path.join(os.path.expanduser("~"), ".knowledge_base")
    base_dir = os.path.abspath(base_dir)
    os.makedirs(os.path.join(base_dir, "uploads"), exist_ok=True)
    db_path = os.path.join(base_dir, "knowledge.db").replace("\\", "/")
    return f"sqlite:///{db_path}", base_dir


_db_url, _data_dir = _resolve_paths()


def _parse_cors(origins_raw: str | None) -> list[str]:
    """解析 CORS_ORIGINS 环境变量（支持 JSON 数组或逗号分隔）"""
    if not origins_raw:
        return ["http://localhost:5173", "http://127.0.0.1:8765"]
    try:
        return json.loads(origins_raw)
    except (json.JSONDecodeError, TypeError):
        return [o.strip() for o in origins_raw.split(",") if o.strip()]


class Settings(BaseSettings):
    database_url: str = os.environ.get("DATABASE_URL", _db_url)
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_model_name: str = "deepseek-chat"
    upload_dir: str = os.path.join(_data_dir, "uploads")
    cors_origins: list[str] = _parse_cors(os.environ.get("CORS_ORIGINS"))
    secret_key: str = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")

    class Config:
        env_file = _get_env_file()


settings = Settings()
