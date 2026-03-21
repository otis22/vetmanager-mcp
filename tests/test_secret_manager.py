"""Unit tests for stage 21.3 secret management."""

import secret_manager
from storage_models import VetmanagerConnection


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


def test_encrypt_and_decrypt_secret_payload_roundtrip(monkeypatch):
    """Encrypted payload must roundtrip without exposing plaintext."""
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    payload = {"domain": "clinic", "api_key": "super-secret"}

    encrypted = secret_manager.encrypt_secret_payload(payload)
    decrypted = secret_manager.decrypt_secret_payload(encrypted)

    assert encrypted != "super-secret"
    assert "super-secret" not in encrypted
    assert decrypted == payload


def test_missing_storage_encryption_key_raises(monkeypatch):
    """Secret manager must fail closed when no encryption key is configured."""
    monkeypatch.delenv("STORAGE_ENCRYPTION_KEY", raising=False)
    try:
        secret_manager.encrypt_secret_payload({"api_key": "x"})
    except secret_manager.SecretManagerError as exc:
        assert "STORAGE_ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("SecretManagerError was not raised")


def test_vetmanager_connection_stores_only_encrypted_credentials(monkeypatch):
    """Model helper must persist encrypted blob and recover original payload."""
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    connection = VetmanagerConnection(account_id=1, auth_mode="domain_api_key")

    connection.set_credentials({"domain": "abc", "api_key": "plain-key"})

    assert connection.encrypted_credentials is not None
    assert "plain-key" not in connection.encrypted_credentials
    assert connection.get_credentials() == {"domain": "abc", "api_key": "plain-key"}
