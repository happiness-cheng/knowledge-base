"""Encryption behavior for user-managed AI provider credentials."""

import pytest
from cryptography.fernet import Fernet

from app.services.secret_store import SecretCipher, SecretConfigurationError


def test_secret_cipher_round_trips_with_version_prefix():
    cipher = SecretCipher(Fernet.generate_key().decode())

    encrypted = cipher.encrypt("sk-user-secret")

    assert encrypted.startswith("fernet:v1:")
    assert "sk-user-secret" not in encrypted
    assert cipher.decrypt(encrypted) == "sk-user-secret"


def test_secret_cipher_reads_legacy_plaintext():
    assert SecretCipher("").decrypt("legacy-key") == "legacy-key"


def test_secret_cipher_requires_key_for_write():
    with pytest.raises(SecretConfigurationError, match="AI_KEY_ENCRYPTION_KEY"):
        SecretCipher("").encrypt("sk-user-secret")
