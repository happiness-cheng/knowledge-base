"""Versioned encryption for user-managed provider credentials."""

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


CIPHERTEXT_PREFIX = "fernet:v1:"


class SecretConfigurationError(RuntimeError):
    """Raised when encrypted secrets cannot be safely read or written."""


class SecretCipher:
    def __init__(self, key: str):
        self._fernet = None
        if key:
            try:
                self._fernet = Fernet(key.encode())
            except (AttributeError, TypeError, ValueError) as exc:
                raise SecretConfigurationError(
                    "AI_KEY_ENCRYPTION_KEY is invalid"
                ) from exc

    def encrypt(self, value: str) -> str:
        if not self._fernet:
            raise SecretConfigurationError(
                "AI_KEY_ENCRYPTION_KEY is required before saving a user API key"
            )
        return CIPHERTEXT_PREFIX + self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str | None) -> str | None:
        if not value or not value.startswith(CIPHERTEXT_PREFIX):
            return value
        if not self._fernet:
            raise SecretConfigurationError(
                "AI_KEY_ENCRYPTION_KEY is required to read an encrypted user API key"
            )
        try:
            token = value.removeprefix(CIPHERTEXT_PREFIX).encode()
            return self._fernet.decrypt(token).decode()
        except InvalidToken as exc:
            raise SecretConfigurationError(
                "Stored user API key cannot be decrypted"
            ) from exc


def encrypt_user_api_key(value: str) -> str:
    return SecretCipher(settings.ai_key_encryption_key).encrypt(value)


def decrypt_user_api_key(value: str | None) -> str | None:
    return SecretCipher(settings.ai_key_encryption_key).decrypt(value)
