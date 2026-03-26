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


def test_validate_required_secrets_passes_when_all_set(monkeypatch):
    """validate_required_secrets must not raise when both secrets are present."""
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-session-secret-min-16ch")
    secret_manager.validate_required_secrets()


def test_validate_required_secrets_fails_when_encryption_key_missing(monkeypatch):
    """validate_required_secrets must list STORAGE_ENCRYPTION_KEY when missing."""
    monkeypatch.delenv("STORAGE_ENCRYPTION_KEY", raising=False)
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-session-secret-min-16ch")
    try:
        secret_manager.validate_required_secrets()
    except secret_manager.SecretManagerError as exc:
        assert "STORAGE_ENCRYPTION_KEY" in str(exc)
    else:
        raise AssertionError("SecretManagerError was not raised")


def test_validate_required_secrets_fails_when_session_secret_missing(monkeypatch):
    """validate_required_secrets must list WEB_SESSION_SECRET when missing."""
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
    try:
        secret_manager.validate_required_secrets()
    except secret_manager.SecretManagerError as exc:
        assert "WEB_SESSION_SECRET" in str(exc)
    else:
        raise AssertionError("SecretManagerError was not raised")


def test_validate_required_secrets_lists_all_missing(monkeypatch):
    """validate_required_secrets must list all missing secrets at once."""
    monkeypatch.delenv("STORAGE_ENCRYPTION_KEY", raising=False)
    monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
    try:
        secret_manager.validate_required_secrets()
    except secret_manager.SecretManagerError as exc:
        msg = str(exc)
        assert "STORAGE_ENCRYPTION_KEY" in msg
        assert "WEB_SESSION_SECRET" in msg
    else:
        raise AssertionError("SecretManagerError was not raised")
