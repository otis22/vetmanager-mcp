"""Unit tests for stage 23.1 Vetmanager auth mode abstraction."""

import pytest

from exceptions import AuthError, VetmanagerError
from storage_models import VetmanagerConnection
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    resolve_vetmanager_credentials,
)


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


def test_resolve_domain_api_key_mode_returns_runtime_credentials():
    """domain_api_key mode should yield normalized domain/api_key pair."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode=VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-a", "api_key": "secret-key"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    resolved = resolve_vetmanager_credentials(
        connection,
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    assert resolved.auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
    assert resolved.domain == "clinic-a"
    assert resolved.api_key == "secret-key"
    assert resolved.build_headers()["X-REST-API-KEY"] == "secret-key"
    assert len(resolved.api_key_fingerprint()) == 16


def test_resolve_user_token_mode_returns_runtime_credentials():
    """user_token mode should yield normalized domain/token pair."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-b", "user_token": "user-token-secret", "app_name": "vetmanager-mcp"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    resolved = resolve_vetmanager_credentials(
        connection,
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    assert resolved.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN
    assert resolved.domain == "clinic-b"
    assert resolved.credential == "user-token-secret"
    assert resolved.api_key == "user-token-secret"
    assert resolved.build_headers()["X-USER-TOKEN"] == "user-token-secret"
    assert resolved.build_headers()["X-APP-NAME"] == "vetmanager-mcp"
    assert len(resolved.credential_fingerprint()) == 16


def test_resolve_vetmanager_credentials_rejects_unknown_auth_mode():
    """Unknown Vetmanager auth modes must fail explicitly."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode="unsupported_mode",
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-a", "api_key": "secret-key"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    with pytest.raises(VetmanagerError, match="Unsupported Vetmanager auth mode"):
        resolve_vetmanager_credentials(connection, encryption_key=TEST_ENCRYPTION_KEY)


def test_resolve_domain_api_key_mode_requires_both_domain_and_api_key():
    """domain_api_key mode must reject incomplete payloads."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode=VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-a"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    with pytest.raises(AuthError, match="missing Vetmanager API key"):
        resolve_vetmanager_credentials(connection, encryption_key=TEST_ENCRYPTION_KEY)


def test_resolve_user_token_mode_requires_token():
    """user_token mode must reject incomplete payloads."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-b"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    with pytest.raises(AuthError, match="missing Vetmanager user token"):
        resolve_vetmanager_credentials(connection, encryption_key=TEST_ENCRYPTION_KEY)


def test_resolve_user_token_mode_defaults_missing_app_name_for_legacy_rows():
    """Legacy user_token rows without app_name should fall back to default app name."""
    connection = VetmanagerConnection(
        account_id=1,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status="active",
    )
    connection.set_credentials(
        {"domain": "clinic-b", "user_token": "user-token-secret"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )

    resolved = resolve_vetmanager_credentials(connection, encryption_key=TEST_ENCRYPTION_KEY)
    assert resolved.build_headers()["X-APP-NAME"] == "vetmanager-mcp"
