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


def test_ragflow_backend_requires_base_url_and_api_key():
    config = Settings(_env_file=None, kb_retrieval_backend='ragflow')
    with pytest.raises(RuntimeError, match='RAGFLOW_BASE_URL'):
        config.validate_runtime()
    config = Settings(_env_file=None, kb_retrieval_backend='ragflow',
                      ragflow_base_url='http://ragflow:9380')
    with pytest.raises(RuntimeError, match='RAGFLOW_API_KEY'):
        config.validate_runtime()


def test_ragflow_backend_rejects_non_http_base_url():
    config = Settings(_env_file=None, kb_retrieval_backend='ragflow',
                      ragflow_base_url='ragflow:9380', ragflow_api_key='k')
    with pytest.raises(RuntimeError, match='RAGFLOW_BASE_URL'):
        config.validate_runtime()


def test_ragflow_production_does_not_require_chroma_url():
    config = Settings(
        _env_file=None, app_env='production', secret_key='a'*32,
        ai_key_encryption_key=Fernet.generate_key().decode(),
        kb_retrieval_backend='ragflow', ragflow_base_url='http://ragflow:9380',
        ragflow_api_key='k', kb_chroma_url='',
    )
    config.validate_runtime()


def test_ragflow_retrieval_tuning_defaults_and_bounds():
    config = Settings(_env_file=None)
    assert config.ragflow_keywords_similarity_weight == 0.3
    assert config.ragflow_similarity_threshold == 0.2
    with pytest.raises(ValueError):
        Settings(_env_file=None, ragflow_keywords_similarity_weight=1.1)
    with pytest.raises(ValueError):
        Settings(_env_file=None, ragflow_similarity_threshold=-0.1)
