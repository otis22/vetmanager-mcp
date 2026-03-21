"""Encryption helpers for sensitive storage payloads."""

from __future__ import annotations

import json
import os
from typing import Any, Mapping

from cryptography.fernet import Fernet, InvalidToken


class SecretManagerError(RuntimeError):
    """Raised when secret encryption/decryption cannot be performed safely."""


def get_storage_encryption_key() -> str:
    """Return configured storage encryption key or fail closed."""
    key = os.environ.get("STORAGE_ENCRYPTION_KEY")
    if not key:
        raise SecretManagerError(
            "Missing STORAGE_ENCRYPTION_KEY for encrypted storage payloads."
        )
    return key


def generate_storage_encryption_key() -> str:
    """Generate a Fernet-compatible key for STORAGE_ENCRYPTION_KEY."""
    return Fernet.generate_key().decode("utf-8")


def _get_fernet(key: str | None = None) -> Fernet:
    try:
        return Fernet((key or get_storage_encryption_key()).encode("utf-8"))
    except (ValueError, TypeError) as exc:
        raise SecretManagerError("Invalid STORAGE_ENCRYPTION_KEY format.") from exc


def encrypt_secret_payload(
    payload: Mapping[str, Any],
    *,
    key: str | None = None,
) -> str:
    """Encrypt secret payload to an opaque token suitable for DB storage."""
    serialized = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"))
    token = _get_fernet(key).encrypt(serialized.encode("utf-8"))
    return token.decode("utf-8")


def decrypt_secret_payload(
    encrypted_payload: str,
    *,
    key: str | None = None,
) -> dict[str, Any]:
    """Decrypt storage payload back into structured data."""
    try:
        decrypted = _get_fernet(key).decrypt(encrypted_payload.encode("utf-8"))
    except InvalidToken as exc:
        raise SecretManagerError("Failed to decrypt stored secret payload.") from exc
    return json.loads(decrypted.decode("utf-8"))
