"""HTTP tests for account registration and login/logout web flow."""

import re
from pathlib import Path

import httpx
import pytest
import respx

import storage
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account, ServiceBearerToken, VetmanagerConnection
from web_auth import SESSION_COOKIE_NAME, register_account

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "web-auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    storage.reset_storage_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_register_route_creates_account_and_starts_session(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        response = await client.post(
            "/register",
            data={"email": "owner@example.com", "password": "strong-pass-123"},
        )

    assert response.status_code == 200
    assert "Личный кабинет" in response.text
    assert "owner@example.com" in response.text
    assert SESSION_COOKIE_NAME in client.cookies

    async with storage.get_session_factory()() as session:
        stored = await session.get(Account, 1)

    assert stored is not None
    assert stored.password_hash != "strong-pass-123"
    assert stored.password_hash.startswith("pbkdf2_sha256$")

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_login_logout_flow_requires_valid_credentials(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="doctor@example.com",
            password="correct-horse-battery",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        invalid = await client.post(
            "/login",
            data={"email": "doctor@example.com", "password": "wrong-pass"},
        )
        assert invalid.status_code == 401
        assert "Invalid email or password." in invalid.text

        valid = await client.post(
            "/login",
            data={"email": "doctor@example.com", "password": "correct-horse-battery"},
        )
        assert valid.status_code == 200
        assert "doctor@example.com" in valid.text
        assert SESSION_COOKIE_NAME in client.cookies

        logout = await client.post("/logout", follow_redirects=False)
        assert logout.status_code == 303
        assert logout.headers["location"] == "/"

        account_page = await client.get("/account", follow_redirects=False)
        assert account_page.status_code == 303
        assert account_page.headers["location"] == "/login"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_register_rejects_duplicate_email(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        first = await client.post(
            "/register",
            data={"email": "ops@example.com", "password": "first-pass-123"},
        )
        assert first.status_code == 200

        second = await client.post(
            "/register",
            data={"email": "ops@example.com", "password": "second-pass-456"},
        )

    assert second.status_code == 400
    assert "Account with this email already exists." in second.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_integration_form_saves_active_vetmanager_connection(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="integration@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-a.vetmanager.cloud"}})
    )
    respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        login = await client.post(
            "/login",
            data={"email": "integration@example.com", "password": "integration-pass-123"},
        )
        assert login.status_code == 200

        response = await client.post(
            "/account/integration",
            data={"domain": "clinic-a", "api_key": "secret-key"},
        )

    assert response.status_code == 200
    assert "Vetmanager integration saved successfully." in response.text
    assert "clinic-a" in response.text
    assert "domain_api_key" in response.text
    assert "secret-key" not in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(VetmanagerConnection, 1)

    assert stored is not None
    assert stored.status == "active"
    assert stored.domain == "clinic-a"
    assert stored.encrypted_credentials is not None
    assert "secret-key" not in stored.encrypted_credentials

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_integration_form_shows_safe_error_for_invalid_api_key(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="invalid-key@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-b").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-b.vetmanager.cloud"}})
    )
    respx.get("https://clinic-b.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await client.post(
            "/login",
            data={"email": "invalid-key@example.com", "password": "integration-pass-123"},
        )
        response = await client.post(
            "/account/integration",
            data={"domain": "clinic-b", "api_key": "bad-key"},
        )

    assert response.status_code == 400
    assert "Invalid Vetmanager API key." in response.text
    assert "bad-key" not in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(VetmanagerConnection, 1)

    assert stored is None

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_token_issue_shows_raw_token_once_and_stores_only_hash(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="token-owner@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-token").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-token.vetmanager.cloud"}})
    )
    respx.get("https://clinic-token.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await client.post(
            "/login",
            data={"email": "token-owner@example.com", "password": "integration-pass-123"},
        )
        await client.post(
            "/account/integration",
            data={"domain": "clinic-token", "api_key": "secret-key"},
        )
        response = await client.post(
            "/account/tokens",
            data={"token_name": "Cursor prod", "expires_in_days": "30"},
        )
        follow_up = await client.get("/account")

    assert response.status_code == 200
    assert "Bearer token issued successfully." in response.text
    raw_token_match = re.search(r"vm_st_[A-Za-z0-9_\\-]+", response.text)
    assert raw_token_match is not None
    raw_token = raw_token_match.group(0)
    assert "копируйте его сейчас" in response.text.lower()
    assert follow_up.status_code == 200
    assert raw_token not in follow_up.text
    assert "Cursor prod" in follow_up.text
    assert "active" in follow_up.text
    assert "Current tokens" in follow_up.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(ServiceBearerToken, 1)

    assert stored is not None
    assert stored.name == "Cursor prod"
    assert stored.token_hash
    assert stored.token_prefix.startswith("vm_st_")
    assert stored.expires_at is not None
    assert stored.verify_raw_token(raw_token) is True
    assert stored.token_hash != raw_token
    assert stored.token_hash not in response.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_token_issue_requires_active_integration(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="no-integration@example.com",
            password="token-pass-123",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await client.post(
            "/login",
            data={"email": "no-integration@example.com", "password": "token-pass-123"},
        )
        response = await client.post(
            "/account/tokens",
            data={"token_name": "Blocked token", "expires_in_days": "14"},
        )

    assert response.status_code == 400
    assert "Configure Vetmanager integration before issuing bearer tokens." in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(ServiceBearerToken, 1)

    assert stored is None

    await engine.dispose()
    storage.reset_storage_state()
