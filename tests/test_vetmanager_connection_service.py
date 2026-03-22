"""Unit tests for stage 23.2 Vetmanager connection save/validation service."""

from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
from sqlalchemy import select

from exceptions import AuthError, HostResolutionError
from storage_models import VetmanagerConnection
from vetmanager_connection_service import (
    exchange_user_token,
    save_domain_api_key_connection,
    save_user_login_password_connection,
    save_user_token_connection,
)


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "connection-service.db")


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_persists_validated_active_connection(session_factory):
    """Saving connection should validate host/key and persist encrypted active record."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-a.vetmanager.cloud"}})
    )
    respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        connection = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-a",
            api_key="secret-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.auth_mode == "domain_api_key"
    assert stored.domain == "clinic-a"
    assert stored.encrypted_credentials is not None
    assert "secret-key" not in stored.encrypted_credentials


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_disables_previous_active_connection(session_factory):
    """Account should keep only one active Vetmanager connection after save."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-b").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-b.vetmanager.cloud"}})
    )
    respx.get("https://clinic-b.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        old = VetmanagerConnection(
            account_id=1,
            auth_mode="domain_api_key",
            status="active",
            domain="old-clinic",
        )
        old.set_credentials(
            {"domain": "old-clinic", "api_key": "old-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(old)
        await session.commit()

    async with session_factory() as session:
        new = await save_domain_api_key_connection(
            session,
            account_id=1,
            domain="clinic-b",
            api_key="new-key",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        rows = (
            await session.execute(
                select(VetmanagerConnection)
                .where(VetmanagerConnection.account_id == 1)
                .order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    assert rows[0].status == "disabled"
    assert rows[1].id == new.id
    assert rows[1].status == "active"


@pytest.mark.asyncio
@respx.mock
async def test_save_domain_api_key_connection_rejects_invalid_api_key(session_factory):
    """Connection save should fail safely when API key is invalid."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-c").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-c.vetmanager.cloud"}})
    )
    respx.get("https://clinic-c.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid Vetmanager API key"):
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-c",
                api_key="bad-key",
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
@respx.mock
async def test_save_user_token_connection_persists_encrypted_active_connection(session_factory):
    """User-token mode should validate probe and persist encrypted credentials."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user.vetmanager.cloud"}})
    )
    respx.get("https://clinic-user.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    async with session_factory() as session:
        connection = await save_user_token_connection(
            session,
            account_id=1,
            domain="clinic-user",
            user_token="user-token-secret",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.status == "active"
    assert stored.auth_mode == "user_token"
    assert stored.domain == "clinic-user"
    assert stored.encrypted_credentials is not None
    assert "user-token-secret" not in stored.encrypted_credentials


@pytest.mark.asyncio
@respx.mock
async def test_save_user_token_connection_rejects_invalid_user_token(session_factory):
    """User-token mode should fail safely when runtime token probe is unauthorized."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user-bad").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user-bad.vetmanager.cloud"}})
    )
    respx.get("https://clinic-user-bad.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid Vetmanager user token"):
            await save_user_token_connection(
                session,
                account_id=1,
                domain="clinic-user-bad",
                user_token="bad-user-token",
                app_name="vetmanager-mcp",
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
@respx.mock
async def test_exchange_user_token_uses_multipart_form_and_app_name_without_api_key():
    """Login/password exchange must use multipart form-data with app_name only."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-auth").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-auth.vetmanager.cloud"}})
    )

    captured: dict[str, object] = {}

    def _token_auth_response(request: httpx.Request) -> httpx.Response:
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(200, json={"data": {"token": "fresh-user-token"}})

    respx.post("https://clinic-auth.vetmanager.cloud/token_auth.php").mock(side_effect=_token_auth_response)

    resolved_host, user_token = await exchange_user_token(
        "clinic-auth",
        login="doctor",
        password="doctor-pass-123",
    )

    headers = captured["headers"]
    body = captured["body"]
    assert resolved_host == "https://clinic-auth.vetmanager.cloud"
    assert user_token == "fresh-user-token"
    assert headers["content-type"].startswith("multipart/form-data; boundary=")
    assert "x-rest-api-key" not in {key.lower() for key in headers}
    assert b'name="login"' in body
    assert b'doctor' in body
    assert b'name="password"' in body
    assert b'doctor-pass-123' in body
    assert b'name="app_name"' in body
    assert b'vetmanager-mcp' in body


@pytest.mark.asyncio
@respx.mock
async def test_save_user_login_password_connection_persists_token_without_api_key(session_factory):
    """Saving login/password mode should not require or persist an API key."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-login").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-login.vetmanager.cloud"}})
    )
    respx.post("https://clinic-login.vetmanager.cloud/token_auth.php").mock(
        return_value=httpx.Response(200, json={"data": {"token": "user-token-secret"}})
    )
    captured_validation: dict[str, object] = {}

    def _validation_response(request: httpx.Request) -> httpx.Response:
        captured_validation["headers"] = dict(request.headers)
        return httpx.Response(200, json={"data": []})

    respx.get("https://clinic-login.vetmanager.cloud/rest/api/user").mock(side_effect=_validation_response)

    async with session_factory() as session:
        connection = await save_user_login_password_connection(
            session,
            account_id=1,
            domain="clinic-login",
            login="doctor",
            password="doctor-pass-123",
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        stored = await session.get(VetmanagerConnection, connection.id)

    assert stored is not None
    assert stored.auth_mode == "user_token"
    assert "user-token-secret" not in stored.encrypted_credentials
    assert "doctor-pass-123" not in stored.encrypted_credentials
    assert "vetmanager-mcp" in stored.get_credentials(encryption_key=TEST_ENCRYPTION_KEY).get("app_name", "")
    headers = {key.lower(): value for key, value in captured_validation["headers"].items()}
    assert headers["x-user-token"] == "user-token-secret"
    assert headers["x-app-name"] == "vetmanager-mcp"
    assert "x-rest-api-key" not in headers


@pytest.mark.asyncio
@respx.mock
@pytest.mark.security
async def test_save_domain_api_key_connection_rejects_host_with_path_or_query(session_factory):
    """Billing-resolved host must stay a bare origin before probe requests."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-unsafe").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"url": "https://clinic-unsafe.vetmanager.cloud/nested?x=1"}},
        )
    )

    async with session_factory() as session:
        with pytest.raises(HostResolutionError):
            await save_domain_api_key_connection(
                session,
                account_id=1,
                domain="clinic-unsafe",
                api_key="unsafe-key",
                encryption_key=TEST_ENCRYPTION_KEY,
            )
