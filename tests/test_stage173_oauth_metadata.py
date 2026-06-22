"""Stage 173 OAuth discovery metadata tests."""

from __future__ import annotations

import asyncio
import httpx
import pytest
import base64
import hashlib
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from urllib.parse import parse_qs, urlparse

import oauth_service
import storage
import web
from server import mcp
from storage import Base, create_database_engine
from storage_models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
    VetmanagerConnection,
)
from token_scopes import SUPPORTED_TOKEN_SCOPES
from web_auth import (
    SESSION_COOKIE_NAME,
    create_account_session_token,
    register_account,
)
from web_security import reset_web_security_state

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')
REQUEST_STATE_RE = re.compile(r'name="request_state" value="([^"]+)"')
CONNECTION_ID_RE = re.compile(r'name="connection_id" value="([^"]+)"')


def _pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def _prepare_oauth_db(tmp_path, monkeypatch):
    database_path = tmp_path / "oauth-stage173.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _register_account_with_connection(email: str = "oauth-owner@example.com") -> int:
    async with storage.get_session_factory()() as session:
        account = await register_account(
            session,
            email=email,
            password="Integration-Pass-123",
        )
        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="clinic",
        )
        connection.set_credentials(
            {"domain": "clinic", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        session.add(connection)
        await session.commit()
        return account.id


async def _register_oauth_client(client: httpx.AsyncClient) -> str:
    response = await client.post(
        "/oauth/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chat.openai.com/aip/callback"],
            "scope": "clients.read pets.read",
        },
    )
    assert response.status_code == 201
    return response.json()["client_id"]


async def _authorize_and_consent(
    client: httpx.AsyncClient,
    *,
    client_id: str,
    scope: str = "clients.read pets.read",
    state: str = "state-token",
    code_challenge: str,
) -> str:
    consent_response = await client.get(
        "/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": "https://chat.openai.com/aip/callback",
            "resource": "https://test.example.com/mcp",
            "scope": scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        },
    )
    assert consent_response.status_code == 200
    csrf_token = CSRF_RE.search(consent_response.text).group(1)
    request_state = REQUEST_STATE_RE.search(consent_response.text).group(1)
    connection_id = CONNECTION_ID_RE.search(consent_response.text).group(1)
    callback_response = await client.post(
        "/oauth/authorize/consent",
        data={
            "csrf_token": csrf_token,
            "request_state": request_state,
            "connection_id": connection_id,
        },
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    return parse_qs(urlparse(callback_response.headers["location"]).query)["code"][0]


@pytest.mark.asyncio
async def test_oauth_protected_resource_metadata_uses_canonical_mcp_resource(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com/")
    monkeypatch.setenv("MCP_PATH", "/mcp")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["content-security-policy"] == "default-src 'none'"
    payload = response.json()
    assert payload["resource"] == "https://test.example.com/mcp"
    assert payload["authorization_servers"] == ["https://test.example.com"]
    assert payload["resource_documentation"] == "https://test.example.com/"
    assert payload["scopes_supported"] == list(SUPPORTED_TOKEN_SCOPES)


@pytest.mark.asyncio
async def test_oauth_protected_resource_root_alias_matches_mcp_path(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    monkeypatch.setenv("MCP_PATH", "/custom/mcp")
    app = mcp.http_app(path="/custom/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        root_response = await client.get("/.well-known/oauth-protected-resource")
        path_response = await client.get("/.well-known/oauth-protected-resource/mcp")

    assert root_response.status_code == 200
    assert path_response.status_code == 200
    assert root_response.json() == path_response.json()
    assert root_response.json()["resource"] == "https://test.example.com/custom/mcp"


@pytest.mark.asyncio
async def test_oauth_authorization_server_metadata_is_dcr_public_client_v1(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    monkeypatch.setenv("MCP_PATH", "/mcp")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/.well-known/oauth-authorization-server")

    assert response.status_code == 200
    payload = response.json()
    assert payload["issuer"] == "https://test.example.com"
    assert payload["authorization_endpoint"] == "https://test.example.com/oauth/authorize"
    assert payload["token_endpoint"] == "https://test.example.com/oauth/token"
    assert payload["registration_endpoint"] == "https://test.example.com/oauth/register"
    assert "revocation_endpoint" not in payload
    assert payload["response_types_supported"] == ["code"]
    assert payload["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert payload["code_challenge_methods_supported"] == ["S256"]
    assert payload["token_endpoint_auth_methods_supported"] == ["none"]
    assert payload["client_id_metadata_document_supported"] is False
    assert payload["scopes_supported"] == list(SUPPORTED_TOKEN_SCOPES)


@pytest.mark.asyncio
async def test_openid_configuration_alias_matches_authorization_server_metadata(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        oauth_response = await client.get("/.well-known/oauth-authorization-server")
        openid_response = await client.get("/.well-known/openid-configuration")

    assert oauth_response.status_code == 200
    assert openid_response.status_code == 200
    assert openid_response.json() == oauth_response.json()


@pytest.mark.asyncio
async def test_oauth_dcr_registers_public_client(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "clients.read pets.read",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["client_id"].startswith("vm_oc_")
    assert "client_secret" not in payload
    assert payload["redirect_uris"] == ["https://chat.openai.com/aip/callback"]
    assert payload["token_endpoint_auth_method"] == "none"
    assert payload["grant_types"] == ["authorization_code", "refresh_token"]
    assert payload["response_types"] == ["code"]
    assert payload["scope"] == "clients.read pets.read"
    assert isinstance(payload["client_id_issued_at"], int)

    async with storage.get_session_factory()() as session:
        stored = await session.scalar(select(OAuthClient).where(OAuthClient.client_id == payload["client_id"]))

    assert stored is not None
    assert stored.client_name == "ChatGPT"
    assert stored.redirect_uris_json == '["https://chat.openai.com/aip/callback"]'
    assert stored.scope == "clients.read pets.read"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_dcr_rejects_unsafe_redirect_uri(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "Unsafe",
                "redirect_uris": ["http://evil.example.com/callback"],
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_dcr_rejects_private_client_auth_method(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "Private",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "token_endpoint_auth_method": "client_secret_basic",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_dcr_rate_limits_by_resolved_client_ip(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("OAUTH_DCR_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("OAUTH_DCR_RATE_LIMIT_WINDOW_SECONDS", "60")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    payload = {
        "client_name": "ChatGPT",
        "redirect_uris": ["https://chat.openai.com/aip/callback"],
    }

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post("/oauth/register", json=payload)
        second_response = await client.post("/oauth/register", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 429
    assert second_response.json()["error"] == "temporarily_unavailable"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_dcr_duplicate_cap_is_not_keyed_only_by_redirect_uri(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("OAUTH_DCR_RATE_LIMIT_ATTEMPTS", "10")
    monkeypatch.setenv("OAUTH_DCR_RATE_LIMIT_WINDOW_SECONDS", "60")
    monkeypatch.setattr(oauth_service, "OAUTH_DCR_DUPLICATE_LIMIT", 1)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    redirect_uris = ["https://chat.openai.com/aip/callback"]

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/oauth/register",
            json={"client_name": "ChatGPT one", "redirect_uris": redirect_uris},
        )
        same_metadata_response = await client.post(
            "/oauth/register",
            json={"client_name": "ChatGPT one", "redirect_uris": redirect_uris},
        )
        shared_redirect_response = await client.post(
            "/oauth/register",
            json={"client_name": "ChatGPT two", "redirect_uris": redirect_uris},
        )

    assert first_response.status_code == 201
    assert same_metadata_response.status_code == 429
    assert same_metadata_response.json()["error"] == "temporarily_unavailable"
    assert shared_redirect_response.status_code == 201

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_authorize_without_session_redirects_to_login_with_next(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client_id = await _register_oauth_client(client)
        response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": "clients.read",
                "state": "state-123",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
            follow_redirects=False,
        )

    assert response.status_code == 303
    location = response.headers["location"]
    assert location.startswith("/login?next=")
    next_value = parse_qs(urlparse(location).query)["next"][0]
    assert next_value.startswith("/oauth/authorize?")
    assert "state=state-123" in next_value

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_authorize_consent_creates_code_bound_to_connection(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection()
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(
            SESSION_COOKIE_NAME,
            create_account_session_token(account_id),
            path="/",
        )
        client_id = await _register_oauth_client(client)
        consent_response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": "clients.read pets.read",
                "state": "state-456",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
        )
        csrf_token = CSRF_RE.search(consent_response.text).group(1)
        request_state = REQUEST_STATE_RE.search(consent_response.text).group(1)
        connection_id = CONNECTION_ID_RE.search(consent_response.text).group(1)
        callback_response = await client.post(
            "/oauth/authorize/consent",
            data={
                "csrf_token": csrf_token,
                "request_state": request_state,
                "connection_id": connection_id,
            },
            follow_redirects=False,
        )

    assert consent_response.status_code == 200
    assert "ChatGPT access" in consent_response.text
    assert callback_response.status_code == 303
    callback_url = urlparse(callback_response.headers["location"])
    callback_query = parse_qs(callback_url.query)
    assert callback_url.scheme == "https"
    assert callback_url.netloc == "chat.openai.com"
    assert callback_query["state"] == ["state-456"]
    raw_code = callback_query["code"][0]
    assert raw_code.startswith("vm_oac_")

    async with storage.get_session_factory()() as session:
        stored_code = await session.scalar(select(OAuthAuthorizationCode))

    assert stored_code is not None
    assert stored_code.code_prefix == raw_code[:12]
    assert stored_code.client_id == client_id
    assert stored_code.redirect_uri == "https://chat.openai.com/aip/callback"
    assert stored_code.resource == "https://test.example.com/mcp"
    assert stored_code.scope == "clients.read pets.read"
    assert stored_code.account_id == account_id
    assert stored_code.vetmanager_connection_id == int(connection_id)

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_exchange_refresh_rotation_and_reuse_revocation(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="token-owner@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(
            SESSION_COOKIE_NAME,
            create_account_session_token(account_id),
            path="/",
        )
        client_id = await _register_oauth_client(client)
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            code_challenge=_pkce_challenge(verifier),
        )
        token_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "code_verifier": verifier,
            },
        )
        replay_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "code_verifier": verifier,
            },
        )
        first_payload = token_response.json()
        refresh_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first_payload["refresh_token"],
                "client_id": client_id,
                "resource": "https://test.example.com/mcp",
            },
        )
        reuse_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first_payload["refresh_token"],
                "client_id": client_id,
                "resource": "https://test.example.com/mcp",
            },
        )

    assert token_response.status_code == 200
    assert first_payload["access_token"].startswith("vm_oat_")
    assert first_payload["refresh_token"].startswith("vm_ort_")
    assert first_payload["token_type"] == "Bearer"
    assert first_payload["scope"] == "clients.read pets.read"
    assert replay_response.status_code == 400
    assert replay_response.json()["error"] == "invalid_grant"
    assert refresh_response.status_code == 200
    second_payload = refresh_response.json()
    assert second_payload["refresh_token"] != first_payload["refresh_token"]
    assert second_payload["access_token"] != first_payload["access_token"]
    assert reuse_response.status_code == 400
    assert reuse_response.json()["error"] == "invalid_grant"

    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))
        access_tokens = (await session.execute(select(OAuthAccessToken))).scalars().all()
        refresh_tokens = (await session.execute(select(OAuthRefreshToken))).scalars().all()

    assert grant is not None
    assert grant.status == "revoked"
    assert {token.status for token in access_tokens} == {"revoked"}
    assert {token.status for token in refresh_tokens} == {"revoked"}

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_rejects_malformed_pkce_verifier_without_500(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="bad-pkce@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        client_id = await _register_oauth_client(client)
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            code_challenge=_pkce_challenge(verifier),
        )
        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "code_verifier": "короткий",
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_rejects_exchange_when_client_disabled(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="disabled-client@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        client_id = await _register_oauth_client(client)
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            code_challenge=_pkce_challenge(verifier),
        )
        async with storage.get_session_factory()() as session:
            stored_client = await session.scalar(select(OAuthClient).where(OAuthClient.client_id == client_id))
            stored_client.status = "disabled"
            await session.commit()
        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "code_verifier": verifier,
            },
        )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_rate_limit_is_not_bypassed_by_rotating_client_id(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("OAUTH_TOKEN_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("OAUTH_TOKEN_RATE_LIMIT_WINDOW_SECONDS", "60")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first_response = await client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "client_id": "vm_oc_one"},
        )
        second_response = await client.post(
            "/oauth/token",
            data={"grant_type": "authorization_code", "client_id": "vm_oc_two"},
        )

    assert first_response.status_code == 400
    assert second_response.status_code == 429
    assert second_response.json()["error"] == "temporarily_unavailable"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_concurrent_code_exchange_allows_single_success(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="code-race@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        client_id = await _register_oauth_client(client)
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            code_challenge=_pkce_challenge(verifier),
        )

        async def exchange_once():
            return await client.post(
                "/oauth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": raw_code,
                    "client_id": client_id,
                    "redirect_uri": "https://chat.openai.com/aip/callback",
                    "resource": "https://test.example.com/mcp",
                    "code_verifier": verifier,
                },
            )

        responses = await asyncio.gather(exchange_once(), exchange_once())

    assert sorted(response.status_code for response in responses) == [200, 400]
    assert [response.json().get("error") for response in responses if response.status_code == 400] == [
        "invalid_grant"
    ]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_token_concurrent_refresh_allows_single_success_then_revokes_family(
    tmp_path,
    monkeypatch,
):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="refresh-race@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        client_id = await _register_oauth_client(client)
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            code_challenge=_pkce_challenge(verifier),
        )
        token_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "authorization_code",
                "code": raw_code,
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "code_verifier": verifier,
            },
        )
        refresh_token = token_response.json()["refresh_token"]

        async def refresh_once():
            return await client.post(
                "/oauth/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                    "resource": "https://test.example.com/mcp",
                },
            )

        responses = await asyncio.gather(refresh_once(), refresh_once())

    assert sorted(response.status_code for response in responses) == [200, 400]
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))
        active_access_tokens = (
            await session.execute(select(OAuthAccessToken).where(OAuthAccessToken.status == "active"))
        ).scalars().all()

    assert grant is not None
    assert grant.status == "revoked"
    assert active_access_tokens == []

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_ui_lists_and_revokes_oauth_grant_family(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    account_id = await _register_account_with_connection(email="grant-ui@example.com")

    async def fake_health(*args, **kwargs):
        return "active", "ok"

    monkeypatch.setattr(web, "evaluate_connection_health", fake_health)

    async with storage.get_session_factory()() as session:
        connection = await session.scalar(select(VetmanagerConnection))
        client = OAuthClient(
            client_id="vm_oc_ui",
            client_name="ChatGPT",
            redirect_uris_json='["https://chat.openai.com/aip/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]',
            scope="clients.read",
            status="active",
        )
        session.add(client)
        await session.flush()
        grant = OAuthGrant(
            account_id=account_id,
            vetmanager_connection_id=connection.id,
            client_id=client.client_id,
            scopes_json='["clients.read"]',
            status="active",
        )
        session.add(grant)
        await session.flush()
        session.add_all(
            [
                OAuthAccessToken(
                    grant_id=grant.id,
                    token_prefix="vm_oat_ui",
                    token_hash=hashlib.sha256(b"access").hexdigest(),
                    scope="clients.read",
                    resource="https://test.example.com/mcp",
                    status="active",
                    expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
                ),
                OAuthRefreshToken(
                    grant_id=grant.id,
                    token_prefix="vm_ort_ui",
                    token_hash=hashlib.sha256(b"refresh").hexdigest(),
                    scope="clients.read",
                    resource="https://test.example.com/mcp",
                    status="active",
                    expires_at=datetime.now(timezone.utc) + timedelta(days=30),
                ),
            ]
        )
        await session.commit()
        grant_id = grant.id

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        page_response = await client.get("/account")
        csrf_token = CSRF_RE.search(page_response.text).group(1)
        revoke_response = await client.post(
            f"/account/oauth-grants/{grant_id}/revoke",
            data={"csrf_token": csrf_token},
        )

    assert page_response.status_code == 200
    assert 'data-testid="oauth-grant-list"' in page_response.text
    assert "ChatGPT" in page_response.text
    assert f'action="/account/oauth-grants/{grant_id}/revoke"' in page_response.text
    assert revoke_response.status_code == 200
    assert "ChatGPT connection disconnected successfully." in revoke_response.text

    async with storage.get_session_factory()() as session:
        stored_grant = await session.get(OAuthGrant, grant_id)
        access_tokens = (await session.execute(select(OAuthAccessToken))).scalars().all()
        refresh_tokens = (await session.execute(select(OAuthRefreshToken))).scalars().all()

    assert stored_grant.status == "revoked"
    assert {token.status for token in access_tokens} == {"revoked"}
    assert {token.status for token in refresh_tokens} == {"revoked"}

    await engine.dispose()
    storage.reset_storage_state()
