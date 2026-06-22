"""Unit tests for stage 22.3 runtime credentials resolution."""

from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
import pytest_asyncio

import auth.request as auth_request
import runtime_auth
from bearer_token_manager import generate_bearer_token
from bearer_token_manager import build_token_prefix, hash_bearer_token
from exceptions import AuthError
from storage_models import (
    Account,
    OAuthAccessToken,
    OAuthGrant,
    ServiceBearerToken,
    VetmanagerConnection,
)
from token_scopes import SCOPE_CLIENTS_READ
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
)


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
OAUTH_RAW_ACCESS_TOKEN = "vm_oat_runtime_test_token"


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "runtime-auth.db")


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_prefers_bearer_context(session_factory, monkeypatch):
    """Bearer-based account context should become the primary runtime source."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="bearer-clinic",
        )
        connection.set_credentials(
            {"domain": "bearer-clinic", "api_key": "bearer-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            resolved = await runtime_auth.resolve_runtime_credentials()

    assert resolved.source == "bearer"
    assert resolved.domain == "bearer-clinic"
    assert resolved.api_key == "bearer-key"
    assert resolved.vetmanager_auth.auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
    assert "clients.read" in resolved.scopes
    assert resolved.is_depersonalized is False
    assert resolved.auth_subject_type == "service_bearer"
    assert resolved.auth_subject_id == resolved.bearer_token_id


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_propagates_depersonalized_policy(session_factory, monkeypatch):
    """Runtime credentials should expose bearer depersonalization policy for later sanitizer use."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="bearer-clinic",
        )
        connection.set_credentials(
            {"domain": "bearer-clinic", "api_key": "bearer-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(
            account_id=account.id,
            name="Depersonalized",
            is_depersonalized=True,
        )
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            resolved = await runtime_auth.resolve_runtime_credentials()

    assert resolved.is_depersonalized is True


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_normalizes_user_token_mode(session_factory, monkeypatch):
    """Runtime layer should not care whether bearer resolves to API key or user token."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
            status="active",
            domain="bearer-user-clinic",
        )
        connection.set_credentials(
            {
                "domain": "bearer-user-clinic",
                "user_token": "user-token-secret",
                "app_name": "vetmanager-mcp",
            },
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            resolved = await runtime_auth.resolve_runtime_credentials()

    assert resolved.source == "bearer"
    assert resolved.domain == "bearer-user-clinic"
    assert resolved.api_key == "user-token-secret"
    assert resolved.vetmanager_auth.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN
    assert resolved.vetmanager_auth.build_headers()["X-USER-TOKEN"] == "user-token-secret"
    assert resolved.vetmanager_auth.build_headers()["X-APP-NAME"] == "vetmanager-mcp"


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_accepts_oauth_access_token(session_factory, monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        account = Account(email="oauth@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="oauth-clinic",
        )
        connection.set_credentials(
            {"domain": "oauth-clinic", "api_key": "oauth-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id="vm_oc_test",
            scopes_json='["clients.read"]',
            status="active",
        )
        session.add(grant)
        await session.flush()
        access_token = OAuthAccessToken(
            grant_id=grant.id,
            token_prefix=build_token_prefix(OAUTH_RAW_ACCESS_TOKEN),
            token_hash=hash_bearer_token(OAUTH_RAW_ACCESS_TOKEN),
            scope="clients.read",
            resource="https://test.example.com/mcp",
            status="active",
            expires_at=now + timedelta(minutes=30),
        )
        session.add(access_token)
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {OAUTH_RAW_ACCESS_TOKEN}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            resolved = await runtime_auth.resolve_runtime_credentials()

    assert resolved.source == "oauth"
    assert resolved.domain == "oauth-clinic"
    assert resolved.api_key == "oauth-key"
    assert resolved.account_id == 1
    assert resolved.bearer_token_id is None
    assert resolved.connection_id == 1
    assert resolved.scopes == ("clients.read",)
    assert resolved.auth_subject_type == "oauth_access_token"
    assert resolved.auth_subject_id == 1


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_rejects_oauth_wrong_resource(session_factory, monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        account = Account(email="oauth-wrong-resource@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="oauth-clinic",
        )
        connection.set_credentials(
            {"domain": "oauth-clinic", "api_key": "oauth-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id="vm_oc_test",
            scopes_json='["clients.read"]',
            status="active",
        )
        session.add(grant)
        await session.flush()
        session.add(
            OAuthAccessToken(
                grant_id=grant.id,
                token_prefix=build_token_prefix(OAUTH_RAW_ACCESS_TOKEN),
                token_hash=hash_bearer_token(OAUTH_RAW_ACCESS_TOKEN),
                scope="clients.read",
                resource="https://other.example.com/mcp",
                status="active",
                expires_at=now + timedelta(minutes=30),
            )
        )
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {OAUTH_RAW_ACCESS_TOKEN}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            with pytest.raises(AuthError) as exc_info:
                await runtime_auth.resolve_runtime_credentials()

    assert exc_info.value.status_code == 401
    assert exc_info.value.error_code == "invalid_token"
    assert "resource_metadata=\"https://test.example.com/.well-known/oauth-protected-resource/mcp\"" in (
        exc_info.value.details["www_authenticate"]
    )
    assert exc_info.value.details["mcp/www_authenticate"] == [
        exc_info.value.details["www_authenticate"]
    ]


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_requires_bearer_header():
    """Runtime auth is bearer-only once legacy header fallback is removed."""
    with patch.object(auth_request, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError, match="Missing Authorization"):
            await runtime_auth.resolve_runtime_credentials()


@pytest.mark.asyncio
async def test_vetmanager_client_uses_bearer_runtime_credentials(session_factory, monkeypatch):
    """Client should lazily resolve credentials from bearer account context."""
    import httpx
    import respx
    from vetmanager_client import VetmanagerClient

    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="runtime-clinic",
        )
        connection.set_credentials(
            {"domain": "runtime-clinic", "api_key": "runtime-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            captured_request = None

            def capture(req: httpx.Request) -> httpx.Response:
                nonlocal captured_request
                captured_request = req
                return httpx.Response(200, json={"data": []})

            with respx.mock:
                respx.get("https://billing-api.vetmanager.cloud/host/runtime-clinic").mock(
                    return_value=httpx.Response(
                        200,
                        json={"data": {"url": "https://runtime.vetmanager.cloud"}},
                    )
                )
                respx.get("https://runtime.vetmanager.cloud/rest/api/client").mock(side_effect=capture)

                client = VetmanagerClient()
                await client.get("/rest/api/client")

    assert client._auth_source == "bearer"
    assert client._domain == "runtime-clinic"
    assert client._api_key == "runtime-key"
    assert captured_request is not None
    assert captured_request.headers["X-REST-API-KEY"] == "runtime-key"


@pytest.mark.security
@pytest.mark.asyncio
async def test_vetmanager_client_rejects_request_without_required_scope(session_factory, monkeypatch):
    """Client should enforce coarse-grained bearer scopes before upstream request."""
    from vetmanager_client import VetmanagerClient

    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="runtime-clinic",
        )
        connection.set_credentials(
            {"domain": "runtime-clinic", "api_key": "runtime-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Scoped token")
        token.set_raw_token(raw_token)
        token.set_scopes([SCOPE_CLIENTS_READ])
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            client = VetmanagerClient()
            with pytest.raises(AuthError, match="finance.read"):
                await client.get("/rest/api/invoice")


@pytest.mark.asyncio
async def test_vetmanager_client_uses_user_token_runtime_credentials(session_factory, monkeypatch):
    """Client transport should consume normalized runtime credentials for user_token mode too."""
    import httpx
    import respx
    from vetmanager_client import VetmanagerClient

    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
            status="active",
            domain="runtime-user-clinic",
        )
        connection.set_credentials(
            {
                "domain": "runtime-user-clinic",
                "user_token": "runtime-user-token",
                "app_name": "vetmanager-mcp",
            },
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            captured_request = None

            def capture(req: httpx.Request) -> httpx.Response:
                nonlocal captured_request
                captured_request = req
                return httpx.Response(200, json={"data": []})

            with respx.mock:
                respx.get("https://billing-api.vetmanager.cloud/host/runtime-user-clinic").mock(
                    return_value=httpx.Response(
                        200,
                        json={"data": {"url": "https://runtime-user.vetmanager.cloud"}},
                    )
                )
                respx.get("https://runtime-user.vetmanager.cloud/rest/api/user").mock(
                    side_effect=capture
                )

                client = VetmanagerClient()
                await client.get("/rest/api/user")

    assert client._auth_source == "bearer"
    assert client._domain == "runtime-user-clinic"
    assert client._api_key == "runtime-user-token"
    assert captured_request is not None
    assert captured_request.headers["X-USER-TOKEN"] == "runtime-user-token"
    assert captured_request.headers["X-APP-NAME"] == "vetmanager-mcp"
