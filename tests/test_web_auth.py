"""HTTP tests for account registration and login/logout web flow."""

from datetime import datetime, timezone
import re
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

import storage
from bearer_auth import resolve_bearer_auth_context
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account, ServiceBearerToken, TokenUsageLog, TokenUsageStat, VetmanagerConnection
from web_security import reset_web_security_state
from web_auth import SESSION_COOKIE_NAME, get_web_session_secret, register_account, set_account_session_cookie

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "web-auth.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def _extract_csrf_token(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


async def _post_with_csrf(
    client: httpx.AsyncClient,
    path: str,
    data: dict[str, str],
    *,
    page_path: str | None = None,
    follow_redirects: bool | None = None,
) -> httpx.Response:
    csrf_page = await client.get(page_path or path)
    token = _extract_csrf_token(csrf_page.text)
    request_data = dict(data)
    request_data["csrf_token"] = token
    if follow_redirects is None:
        return await client.post(path, data=request_data)
    return await client.post(path, data=request_data, follow_redirects=follow_redirects)


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
        response = await _post_with_csrf(
            client,
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


def test_get_web_session_secret_requires_config(monkeypatch):
    monkeypatch.delenv("WEB_SESSION_SECRET", raising=False)
    monkeypatch.delenv("STORAGE_ENCRYPTION_KEY", raising=False)

    with pytest.raises(RuntimeError, match="WEB_SESSION_SECRET"):
        get_web_session_secret()


def test_set_account_session_cookie_uses_strict_secure_defaults(monkeypatch):
    from starlette.responses import Response

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.delenv("WEB_SESSION_SECURE", raising=False)
    monkeypatch.delenv("WEB_SESSION_SAMESITE", raising=False)

    response = Response()
    set_account_session_cookie(response, 1)

    set_cookie_header = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie_header
    assert "secure" in set_cookie_header
    assert "samesite=strict" in set_cookie_header


@pytest.mark.asyncio
async def test_register_page_sets_csrf_cookie_and_security_headers(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/register")

    assert response.status_code == 200
    assert "vm_csrf" in client.cookies
    assert 'name="csrf_token"' in response.text
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "default-src 'self'" in response.headers["content-security-policy"]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_register_route_rejects_missing_csrf_token(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await client.get("/register")
        response = await client.post(
            "/register",
            data={"email": "owner@example.com", "password": "strong-pass-123"},
        )

    assert response.status_code == 403
    assert "Invalid CSRF token." in response.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_logout_rejects_mismatched_csrf_token(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="logout@example.com",
            password="correct-horse-battery",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "logout@example.com", "password": "correct-horse-battery"},
        )
        response = await client.post("/logout", data={"csrf_token": "bad-token"}, follow_redirects=False)

    assert response.status_code == 403

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
            data={
                "email": "doctor@example.com",
                "password": "wrong-pass",
                "csrf_token": _extract_csrf_token((await client.get("/login")).text),
            },
        )
        assert invalid.status_code == 401
        assert "Invalid email or password." in invalid.text

        valid = await _post_with_csrf(
            client,
            "/login",
            data={"email": "doctor@example.com", "password": "correct-horse-battery"},
        )
        assert valid.status_code == 200
        assert "doctor@example.com" in valid.text
        assert SESSION_COOKIE_NAME in client.cookies

        logout = await _post_with_csrf(
            client,
            "/logout",
            data={},
            page_path="/account",
            follow_redirects=False,
        )
        assert logout.status_code == 303
        assert logout.headers["location"] == "/"

        account_page = await client.get("/account", follow_redirects=False)
        assert account_page.status_code == 303
        assert account_page.headers["location"] == "/login"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_login_rate_limit_returns_429_after_repeated_failures(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("WEB_LOGIN_RATE_LIMIT_ATTEMPTS", "2")
    monkeypatch.setenv("WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")
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
        first = await _post_with_csrf(
            client,
            "/login",
            data={"email": "doctor@example.com", "password": "wrong-pass"},
        )
        second = await _post_with_csrf(
            client,
            "/login",
            data={"email": "doctor@example.com", "password": "wrong-pass"},
        )
        third = await _post_with_csrf(
            client,
            "/login",
            data={"email": "doctor@example.com", "password": "wrong-pass"},
        )

    assert first.status_code == 401
    assert second.status_code == 401
    assert third.status_code == 429
    assert "Too many login attempts." in third.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_register_rate_limit_returns_429_after_repeated_attempts(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("WEB_REGISTER_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("WEB_REGISTER_RATE_LIMIT_WINDOW_SECONDS", "60")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        first = await _post_with_csrf(
            client,
            "/register",
            data={"email": "first@example.com", "password": "first-pass-123"},
        )
        second = await _post_with_csrf(
            client,
            "/register",
            data={"email": "second@example.com", "password": "second-pass-123"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert "Too many registration attempts." in second.text

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
        first = await _post_with_csrf(
            client,
            "/register",
            data={"email": "ops@example.com", "password": "first-pass-123"},
        )
        assert first.status_code == 200

        second = await _post_with_csrf(
            client,
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
        login = await _post_with_csrf(
            client,
            "/login",
            data={"email": "integration@example.com", "password": "integration-pass-123"},
        )
        assert login.status_code == 200

        response = await _post_with_csrf(
            client,
            "/account/integration",
            data={
                "auth_mode": "domain_api_key",
                "domain": "clinic-a",
                "api_key": "secret-key",
            },
            page_path="/account",
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
async def test_account_page_shows_privacy_and_reauth_notices(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="notices@example.com",
            password="integration-pass-123",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "notices@example.com", "password": "integration-pass-123"},
        )
        response = await client.get("/account")

    assert response.status_code == 200
    assert "не сохраняет бизнес-данные Vetmanager" in response.text
    assert "логин и пароль Vetmanager не сохраняются" in response.text
    assert "при смене пароля в Vetmanager" in response.text
    assert "Выберите способ авторизации Vetmanager" in response.text
    assert "Подключить по API key" in response.text
    assert "Подключить по логину и паролю" in response.text
    assert "Vetmanager login" in response.text
    assert "Vetmanager password" in response.text
    assert "Vetmanager user token" not in response.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_page_shows_onboarding_wizard_for_new_account(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="wizard@example.com",
            password="integration-pass-123",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "wizard@example.com", "password": "integration-pass-123"},
        )
        response = await client.get("/account")

    assert response.status_code == 200
    assert "Сначала подключите Vetmanager" in response.text
    assert 'data-auth-wizard="true"' in response.text
    assert 'value="domain_api_key"' in response.text
    assert 'value="user_token"' in response.text
    assert 'id="auth-mode-domain-api-key"' in response.text
    assert 'id="auth-mode-user-token"' in response.text
    assert 'data-mode-panel="domain_api_key"' in response.text
    assert 'data-mode-panel="user_token"' in response.text
    assert "Подключить по API key" in response.text
    assert "Подключить по логину и паролю" in response.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_integration_form_exchanges_login_password_into_user_token(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="user-token@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user.vetmanager.cloud"}})
    )
    respx.post("https://clinic-user.vetmanager.cloud/token_auth.php").mock(
        return_value=httpx.Response(200, json={"data": {"token": "user-token-secret"}})
    )
    respx.get("https://clinic-user.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "user-token@example.com", "password": "integration-pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/integration",
            data={
                "auth_mode": "user_token",
                "domain": "clinic-user",
                "api_key": "rest-api-key",
                "vm_login": "doctor",
                "vm_password": "doctor-pass-123",
            },
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Vetmanager integration saved successfully." in response.text
    assert "clinic-user" in response.text
    assert "user_token" in response.text
    assert "user-token-secret" not in response.text
    assert "rest-api-key" not in response.text
    assert "doctor-pass-123" not in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(VetmanagerConnection, 1)

    assert stored is not None
    assert stored.status == "active"
    assert stored.domain == "clinic-user"
    assert stored.auth_mode == "user_token"
    assert stored.encrypted_credentials is not None
    assert "user-token-secret" not in stored.encrypted_credentials
    assert "rest-api-key" not in stored.encrypted_credentials
    assert "doctor-pass-123" not in stored.encrypted_credentials

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_integration_form_shows_safe_error_for_failed_login_password_exchange(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="invalid-user-token@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-user-bad").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-user-bad.vetmanager.cloud"}})
    )
    respx.post("https://clinic-user-bad.vetmanager.cloud/token_auth.php").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "invalid-user-token@example.com", "password": "integration-pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/integration",
            data={
                "auth_mode": "user_token",
                "domain": "clinic-user-bad",
                "api_key": "rest-api-key",
                "vm_login": "doctor",
                "vm_password": "bad-password",
            },
            page_path="/account",
        )

    assert response.status_code == 400
    assert "Invalid Vetmanager login, password or API key." in response.text
    assert "rest-api-key" not in response.text
    assert "doctor" not in response.text
    assert "bad-password" not in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(VetmanagerConnection, 1)

    assert stored is None

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
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "invalid-key@example.com", "password": "integration-pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-b", "api_key": "bad-key"},
            page_path="/account",
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
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "token-owner@example.com", "password": "integration-pass-123"},
        )
        await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-token", "api_key": "secret-key"},
            page_path="/account",
        )
        response = await _post_with_csrf(
            client,
            "/account/tokens",
            data={"token_name": "Cursor prod", "expires_in_days": "30"},
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Bearer token issued successfully." in response.text
    assert 'id="issued-token-panel"' in response.text
    assert "Скопировать токен" in response.text
    raw_token_match = re.search(r"vm_st_[A-Za-z0-9_\\-]+", response.text)
    assert raw_token_match is not None
    raw_token = raw_token_match.group(0)
    assert "копируйте его сейчас" in response.text.lower()
    assert response.text.index('id="issued-token-panel"') < response.text.index("Bearer token issuance")

    used_at = datetime(2026, 3, 21, 14, 30, tzinfo=timezone.utc)
    async with storage.get_session_factory()() as session:
        await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
            now=used_at,
        )

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "token-owner@example.com", "password": "integration-pass-123"},
        )
        follow_up = await client.get("/account")

    assert follow_up.status_code == 200
    assert raw_token not in follow_up.text
    assert "Cursor prod" in follow_up.text
    assert "active" in follow_up.text
    assert "Current tokens" in follow_up.text
    assert "2026-03-21 14:30 UTC" in follow_up.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(ServiceBearerToken, 1)
        logs = (
            await session.execute(
                select(TokenUsageLog).where(TokenUsageLog.bearer_token_id == 1)  # type: ignore[name-defined]
            )
        ).scalars().all()
        stats = await session.scalar(
            select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == 1)
        )

    assert stored is not None
    assert stored.name == "Cursor prod"
    assert stored.token_hash
    assert stored.token_prefix.startswith("vm_st_")
    assert stored.expires_at is not None
    assert stored.verify_raw_token(raw_token) is True
    assert stored.token_hash != raw_token
    assert stored.token_hash not in response.text
    assert stats is not None
    assert stats.request_count == 1
    assert [log.event_type for log in logs] == ["token_created", "token_auth_succeeded"]
    assert raw_token not in (logs[0].details_json or "")
    assert raw_token not in (logs[1].details_json or "")

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
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "no-integration@example.com", "password": "token-pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/tokens",
            data={"token_name": "Blocked token", "expires_in_days": "14"},
            page_path="/account",
        )

    assert response.status_code == 400
    assert "Configure Vetmanager integration before issuing bearer tokens." in response.text

    async with storage.get_session_factory()() as session:
        stored = await session.get(ServiceBearerToken, 1)

    assert stored is None

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_token_revoke_updates_status_and_writes_audit_log(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="revoke-owner@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-revoke").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-revoke.vetmanager.cloud"}})
    )
    respx.get("https://clinic-revoke.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "revoke-owner@example.com", "password": "integration-pass-123"},
        )
        await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-revoke", "api_key": "secret-key"},
            page_path="/account",
        )
        created = await _post_with_csrf(
            client,
            "/account/tokens",
            data={"token_name": "Disposable token", "expires_in_days": "7"},
            page_path="/account",
        )
        raw_token = re.search(r"vm_st_[A-Za-z0-9_\\-]+", created.text).group(0)  # type: ignore[union-attr]
        revoked = await _post_with_csrf(
            client,
            "/account/tokens/1/revoke",
            data={},
            page_path="/account",
        )

    assert revoked.status_code == 200
    assert "Bearer token revoked successfully." in revoked.text
    assert "revoked" in revoked.text
    assert raw_token not in revoked.text

    async with storage.get_session_factory()() as session:
        token = await session.get(ServiceBearerToken, 1)
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert token is not None
    assert token.status == "revoked"
    assert token.revoked_at is not None
    assert [log.event_type for log in logs] == ["token_created", "token_revoked"]
    assert raw_token not in (logs[0].details_json or "")
    assert raw_token not in (logs[1].details_json or "")

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_token_logs_capture_request_metadata(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="meta-owner@example.com",
            password="integration-pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-meta").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-meta.vetmanager.cloud"}})
    )
    respx.get("https://clinic-meta.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
        headers={"user-agent": "audit-test-agent"},
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "meta-owner@example.com", "password": "integration-pass-123"},
        )
        await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-meta", "api_key": "secret-key"},
            page_path="/account",
        )
        await _post_with_csrf(
            client,
            "/account/tokens",
            data={"token_name": "Meta token", "expires_in_days": "7"},
            page_path="/account",
        )
        await _post_with_csrf(
            client,
            "/account/tokens/1/revoke",
            data={},
            page_path="/account",
        )

    async with storage.get_session_factory()() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert [log.event_type for log in logs] == ["token_created", "token_revoked"]
    assert logs[0].user_agent == "audit-test-agent"
    assert logs[1].user_agent == "audit-test-agent"
    assert logs[0].ip_address is not None
    assert logs[1].ip_address is not None

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_page_marks_expired_token_via_cleanup_sweep(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    expired_at = datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc)

    async with storage.get_session_factory()() as session:
        account = await register_account(
            session,
            email="expired-owner@example.com",
            password="integration-pass-123",
        )
        token = ServiceBearerToken(
            account_id=account.id,
            name="Old token",
            token_prefix="vm_st_old",
            token_hash="hash",
            status="active",
            expires_at=expired_at,
        )
        session.add(token)
        await session.commit()

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "expired-owner@example.com", "password": "integration-pass-123"},
        )
        account_page = await client.get("/account")

    assert account_page.status_code == 200
    assert "Old token" in account_page.text
    assert "expired" in account_page.text

    async with storage.get_session_factory()() as session:
        token = await session.get(ServiceBearerToken, 1)
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert token is not None
    assert token.status == "expired"
    assert [log.event_type for log in logs] == ["token_expired"]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_account_page_marks_invalid_user_token_connection_as_reauth_required(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)

    async with storage.get_session_factory()() as session:
        account = await register_account(
            session,
            email="reauth-owner@example.com",
            password="integration-pass-123",
        )
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="user_token",
            status="active",
            domain="clinic-reauth",
        )
        connection.set_credentials(
            {"domain": "clinic-reauth", "user_token": "stale-user-token"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.commit()

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-reauth").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-reauth.vetmanager.cloud"}})
    )
    respx.get("https://clinic-reauth.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "reauth-owner@example.com", "password": "integration-pass-123"},
        )
        response = await client.get("/account")

    assert response.status_code == 200
    assert "reauth_required" in response.text
    assert "Повторная авторизация требуется" in response.text
    assert "Переавторизоваться и обновить токен" in response.text

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_reauth_submit_replaces_invalid_user_token_connection(tmp_path: Path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)

    async with storage.get_session_factory()() as session:
        account = await register_account(
            session,
            email="reauth-submit@example.com",
            password="integration-pass-123",
        )
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="user_token",
            status="active",
            domain="clinic-rotate",
        )
        connection.set_credentials(
            {"domain": "clinic-rotate", "user_token": "stale-user-token"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.commit()

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-rotate").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-rotate.vetmanager.cloud"}})
    )
    respx.post("https://clinic-rotate.vetmanager.cloud/token_auth.php").mock(
        return_value=httpx.Response(200, json={"data": {"token": "fresh-user-token"}})
    )
    respx.get("https://clinic-rotate.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
        follow_redirects=True,
    ) as client:
        await _post_with_csrf(
            client,
            "/login",
            data={"email": "reauth-submit@example.com", "password": "integration-pass-123"},
        )
        response = await _post_with_csrf(
            client,
            "/account/integration/reauth",
            data={
                "auth_mode": "user_token",
                "domain": "clinic-rotate",
                "api_key": "rest-api-key",
                "vm_login": "doctor",
                "vm_password": "new-password-123",
            },
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Vetmanager integration re-authorized successfully." in response.text
    assert "fresh-user-token" not in response.text
    assert "new-password-123" not in response.text

    async with storage.get_session_factory()() as session:
        connections = (
            await session.execute(
                select(VetmanagerConnection).order_by(VetmanagerConnection.id.asc())
            )
        ).scalars().all()

    assert len(connections) == 2
    assert connections[0].status == "disabled"
    assert connections[1].status == "active"

    await engine.dispose()
    storage.reset_storage_state()
