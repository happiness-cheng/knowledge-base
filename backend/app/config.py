import os
import sys
import json
from typing import Annotated, Literal

from cryptography.fernet import Fernet
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
DEFAULT_DEVELOPMENT_SECRET_KEY = "dev-secret-change-in-production"


def _parse_cors(origins_raw: str | None) -> list[str]:
    """解析 CORS_ORIGINS 环境变量（支持 JSON 数组或逗号分隔）"""
    if not origins_raw:
        return ["http://localhost:5173", "http://127.0.0.1:8765"]
    try:
        return json.loads(origins_raw)
    except (json.JSONDecodeError, TypeError):
        return [o.strip() for o in origins_raw.split(",") if o.strip()]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_get_env_file(), extra="ignore")

    app_env: Literal["development", "production"] = "development"
    database_url: str = _db_url
    ai_api_key: str = ""
    ai_base_url: str = "https://api.deepseek.com/v1"
    ai_model_name: str = "deepseek-chat"
    ai_key_encryption_key: str = ""
    upload_dir: str = os.path.join(_data_dir, "uploads")
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: _parse_cors(None)
    )
    secret_key: str = DEFAULT_DEVELOPMENT_SECRET_KEY

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if isinstance(value, list):
            return value
        return _parse_cors(value)

    def validate_runtime(self):
        if self.app_env != "production":
            return
        if self.secret_key == DEFAULT_DEVELOPMENT_SECRET_KEY or len(self.secret_key) < 32:
            raise RuntimeError(
                "SECRET_KEY must be a non-default value with at least 32 characters in production"
            )
        try:
            Fernet(self.ai_key_encryption_key.encode())
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "AI_KEY_ENCRYPTION_KEY must be a valid Fernet key in production"
            ) from exc


settings = Settings()
