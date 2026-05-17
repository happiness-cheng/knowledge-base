import os
import sys
from pydantic_settings import BaseSettings


def _get_env_file():
    if getattr(sys, "frozen", False):
        return None
    return os.environ.get("ENV_FILE", ".env")


def _resolve_paths():
    """Resolve database and upload paths to absolute paths."""
    # Always use ~/.knowledge_base to keep data consistent
    base_dir = os.path.join(os.path.expanduser("~"), ".knowledge_base")
    base_dir = os.path.abspath(base_dir)
    os.makedirs(os.path.join(base_dir, "uploads"), exist_ok=True)
    db_path = os.path.join(base_dir, "knowledge.db").replace("\\", "/")
    return f"sqlite:///{db_path}", base_dir


_db_url, _data_dir = _resolve_paths()


class Settings(BaseSettings):
    database_url: str = _db_url
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com/v1" # Default to DeepSeek, can be overridden in .env
    ai_model_name: str = "deepseek-chat"
    upload_dir: str = os.path.join(_data_dir, "uploads")
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:8765"]

    class Config:
        env_file = _get_env_file()


settings = Settings()
