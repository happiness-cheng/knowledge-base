"""Runtime configuration validation tests."""

import pytest
from cryptography.fernet import Fernet

from app.config import DEFAULT_DEVELOPMENT_SECRET_KEY, Settings


def test_production_rejects_default_secret_and_invalid_fernet_key():
    insecure = Settings(
        _env_file=None,
        app_env="production",
        secret_key=DEFAULT_DEVELOPMENT_SECRET_KEY,
        ai_key_encryption_key=Fernet.generate_key().decode(),
    )
    invalid_key = Settings(
        _env_file=None,
        app_env="production",
        secret_key="a" * 32,
        ai_key_encryption_key="invalid",
    )

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        insecure.validate_runtime()
    with pytest.raises(RuntimeError, match="AI_KEY_ENCRYPTION_KEY"):
        invalid_key.validate_runtime()


def test_production_requires_explicit_index_service():
    config = Settings(_env_file=None, app_env='production', secret_key='a'*32,
                      ai_key_encryption_key=Fernet.generate_key().decode(), kb_chroma_url='')
    with pytest.raises(RuntimeError, match='KB_CHROMA_URL'):
        config.validate_runtime()


def test_production_with_valid_explicit_index_origin_passes_without_connecting():
    config = Settings(_env_file=None, app_env='production', secret_key='a'*32,
                      ai_key_encryption_key=Fernet.generate_key().decode(), kb_chroma_url='http://127.0.0.1:8000')
    config.validate_runtime()
