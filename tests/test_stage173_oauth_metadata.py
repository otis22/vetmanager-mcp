"""Stage 173 OAuth discovery metadata tests."""

from __future__ import annotations

import asyncio
import json
import httpx
import pytest
import base64
import hashlib
import re
import respx
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from fastmcp import Client
from sqlalchemy import select
from urllib.parse import parse_qs, urlparse

import auth.request as auth_request
import oauth_service
import storage
import web
from bearer_token_manager import build_token_prefix, hash_bearer_token
from exceptions import AuthError
from oauth_metadata import OAUTH_SCOPE_OFFLINE_ACCESS, get_oauth_scopes_supported
from server import mcp
from service_metrics import reset_service_metrics, snapshot_service_metrics
from storage import Base, create_database_engine
from depersonalization import REDACTED_EMAIL, REDACTED_NAME, REDACTED_PHONE
from storage_models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthGrant,
    OAuthRefreshToken,
    Account,
    VetmanagerConnection,
)
from tests.runtime_factories import make_runtime_credentials
from token_scopes import LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS, SUPPORTED_TOKEN_SCOPES
from tool_access_registry import PRESET_FULL_ACCESS, PRESET_READ_ONLY, PRESET_REPORT_AI, TOKEN_PRESET_SCOPES
from tool_oauth_security import OAuthChallengeMiddleware, _challenge_result
from tool_scope_security import ScopeDeniedToolError
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


async def _register_oauth_client(
    client: httpx.AsyncClient,
    *,
    scope: str = "clients.read pets.read",
) -> str:
    response = await client.post(
        "/oauth/register",
        json={
            "client_name": "ChatGPT",
            "redirect_uris": ["https://chat.openai.com/aip/callback"],
            "scope": scope,
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
    access_preset: str = PRESET_REPORT_AI,
    confirm_full_access: bool = False,
    privacy_mode: str = "depersonalized",
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
    consent_data = {
        "csrf_token": csrf_token,
        "request_state": request_state,
        "connection_id": connection_id,
        "access_preset": access_preset,
        "privacy_mode": privacy_mode,
    }
    if confirm_full_access:
        consent_data["confirm_full_access"] = "1"
    callback_response = await client.post(
        "/oauth/authorize/consent",
        data=consent_data,
        follow_redirects=False,
    )
    assert callback_response.status_code == 303
    return parse_qs(urlparse(callback_response.headers["location"]).query)["code"][0]


async def _exchange_authorization_code(
    client: httpx.AsyncClient,
    *,
    raw_code: str,
    client_id: str,
    verifier: str,
) -> httpx.Response:
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


def _mock_client_lookup_with_personal_fields() -> None:
    respx.get("https://billing-api.vetmanager.cloud/host/clinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic.vetmanager.cloud"}})
    )
    respx.get("https://clinic.vetmanager.cloud/rest/api/client/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "id": 42,
                    "firstName": "Anna",
                    "phone": "+7 (916) 123-45-67",
                    "email": "anna@example.com",
                }
            },
        )
    )


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
    assert payload["scopes_supported"] == get_oauth_scopes_supported()
    assert OAUTH_SCOPE_OFFLINE_ACCESS in payload["scopes_supported"]
    assert OAUTH_SCOPE_OFFLINE_ACCESS not in SUPPORTED_TOKEN_SCOPES


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
    assert payload["scopes_supported"] == get_oauth_scopes_supported()
    assert OAUTH_SCOPE_OFFLINE_ACCESS in payload["scopes_supported"]
    assert OAUTH_SCOPE_OFFLINE_ACCESS not in SUPPORTED_TOKEN_SCOPES


@pytest.mark.asyncio
async def test_openid_configuration_alias_matches_authorization_server_metadata(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http", stateless_http=True)
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        oauth_response = await client.get("/.well-known/oauth-authorization-server")
        openid_response = await client.get("/.well-known/openid-configuration")

    assert oauth_response.status_code == 200
    assert openid_response.status_code == 200
    assert openid_response.json() == oauth_response.json()


@pytest.mark.asyncio
async def test_mcp_tool_auth_failure_returns_oauth_challenge_meta(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")

    async def _reject_credentials():
        raise AuthError("Invalid authorization.", status_code=401, error_code="invalid_token")

    async def _unexpected_call_next(context):
        raise AssertionError("Auth challenge middleware must not call the tool after auth failure")

    monkeypatch.setattr("tool_oauth_security._is_http_mcp_request", lambda: True)
    monkeypatch.setattr("tool_oauth_security.resolve_runtime_credentials", _reject_credentials)

    response = await OAuthChallengeMiddleware().on_call_tool(
        SimpleNamespace(message=SimpleNamespace(name="get_clients")),
        _unexpected_call_next,
    )
    result = response.to_mcp_result().model_dump(mode="json", by_alias=True)

    assert result["isError"] is True
    assert result["content"][0]["text"] == "Runtime authentication failed."
    challenge = result["_meta"]["mcp/www_authenticate"][0]
    assert 'resource_metadata="https://test.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
    assert 'scope="clients.read"' in challenge
    assert 'error="invalid_token"' in challenge


@pytest.mark.asyncio
async def test_fastmcp_dispatch_preserves_oauth_challenge_meta(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")

    async def _reject_credentials():
        raise AuthError("Invalid authorization.", status_code=401, error_code="invalid_token")

    monkeypatch.setattr("tool_oauth_security._is_http_mcp_request", lambda: True)
    monkeypatch.setattr("tool_oauth_security.resolve_runtime_credentials", _reject_credentials)

    async with Client(mcp) as client:
        result = await client.call_tool("get_clients", {"limit": 1}, raise_on_error=False)

    assert result.is_error is True
    assert result.content[0].text == "Runtime authentication failed."
    challenge = result.meta["mcp/www_authenticate"][0]
    assert 'resource_metadata="https://test.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
    assert 'scope="clients.read"' in challenge
    assert 'error="invalid_token"' in challenge


@pytest.mark.asyncio
async def test_fastmcp_success_path_reuses_middleware_credentials(monkeypatch):
    calls = 0

    async def _resolve_credentials():
        nonlocal calls
        calls += 1
        return make_runtime_credentials("clinic", "secret-key", scopes=("clients.read",))

    monkeypatch.setattr("tool_oauth_security._is_http_mcp_request", lambda: True)
    monkeypatch.setattr("tool_oauth_security.resolve_runtime_credentials", _resolve_credentials)

    async with Client(mcp) as client:
        result = await client.call_tool("get_report_ai_prompt_helper", {}, raise_on_error=False)

    assert result.is_error is False
    assert calls == 1


def test_mcp_tool_scope_denial_returns_insufficient_scope_challenge_meta(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    result = _challenge_result(
        ScopeDeniedToolError(
            "Tool 'get_clients' is not permitted for this token.",
            required_scopes=("clients.read",),
        )
    ).to_mcp_result().model_dump(mode="json", by_alias=True)

    assert result["isError"] is True
    assert "Tool 'get_clients' is not permitted for this token." in result["content"][0]["text"]
    challenge = result["_meta"]["mcp/www_authenticate"][0]
    assert 'resource_metadata="https://test.example.com/.well-known/oauth-protected-resource/mcp"' in challenge
    assert 'scope="clients.read"' in challenge
    assert 'error="insufficient_scope"' in challenge


@pytest.mark.asyncio
async def test_mcp_tool_unknown_name_defers_to_fastmcp_routing(monkeypatch):
    async def _call_next(context):
        return "routed"

    async def _unexpected_credentials():
        raise AssertionError("Unknown tools should not be preflight-authenticated")

    monkeypatch.setattr("tool_oauth_security._is_http_mcp_request", lambda: True)
    monkeypatch.setattr("tool_oauth_security.resolve_runtime_credentials", _unexpected_credentials)

    response = await OAuthChallengeMiddleware().on_call_tool(
        SimpleNamespace(message=SimpleNamespace(name="missing_tool")),
        _call_next,
    )

    assert response == "routed"


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
async def test_oauth_dcr_accepts_offline_access_without_tool_scope_expansion(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT offline",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "token_endpoint_auth_method": "none",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "scope": "clients.read offline_access",
            },
        )
        rejected = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT bad scope",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": "clients.read offline_access unknown.scope",
            },
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["scope"] == "clients.read offline_access"
    assert rejected.status_code == 400
    assert rejected.json()["error"] == "invalid_scope"

    async with storage.get_session_factory()() as session:
        stored = await session.scalar(select(OAuthClient).where(OAuthClient.client_id == payload["client_id"]))

    assert stored is not None
    assert stored.scope == "clients.read offline_access"
    assert oauth_service.normalize_oauth_tool_scopes(stored.scope.split()) == ["clients.read"]

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
async def test_oauth_authorize_accepts_offline_access_for_legacy_registered_client(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-legacy-offline@example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(
            SESSION_COOKIE_NAME,
            create_account_session_token(account_id),
            path="/",
        )
        client_id = await _register_oauth_client(client, scope="clients.read")
        consent_response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": "clients.read offline_access",
                "state": "state-legacy-offline",
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
                "access_preset": PRESET_READ_ONLY,
            },
            follow_redirects=False,
        )

    assert consent_response.status_code == 200
    assert callback_response.status_code == 303
    async with storage.get_session_factory()() as session:
        stored_code = await session.scalar(select(OAuthAuthorizationCode))

    assert stored_code is not None
    assert stored_code.scope == "clients.read offline_access"

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
                "access_preset": PRESET_READ_ONLY,
            },
            follow_redirects=False,
        )

    assert consent_response.status_code == 200
    consent_csp = consent_response.headers["content-security-policy"]
    assert "form-action 'self' https://chatgpt.com https://chat.openai.com" in consent_csp
    assert "ChatGPT access" in consent_response.text
    assert 'data-testid="oauth-access-preset"' in consent_response.text
    assert 'data-testid="oauth-effective-scope-preview"' in consent_response.text
    assert 'data-testid="oauth-privacy-mode"' in consent_response.text
    assert 'data-testid="oauth-privacy-depersonalized"' in consent_response.text
    assert 'data-testid="oauth-privacy-personal-data"' in consent_response.text
    assert "Effective scopes by access level" in consent_response.text
    assert f'value="{PRESET_REPORT_AI}" selected' in consent_response.text
    assert callback_response.status_code == 303
    callback_csp = callback_response.headers["content-security-policy"]
    assert "form-action 'self' https://chatgpt.com https://chat.openai.com" in callback_csp
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
    assert stored_code.access_preset == PRESET_READ_ONLY
    assert stored_code.is_depersonalized is True
    assert stored_code.account_id == account_id
    assert stored_code.vetmanager_connection_id == int(connection_id)

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_consent_narrows_full_request_to_read_only_preset(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-readonly@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    full_scope = " ".join(SUPPORTED_TOKEN_SCOPES)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": full_scope,
            },
        )
        client_id = response.json()["client_id"]
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope=full_scope,
            code_challenge=_pkce_challenge(verifier),
            access_preset=PRESET_READ_ONLY,
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

    assert token_response.status_code == 200
    assert token_response.json()["scope"] == " ".join(TOKEN_PRESET_SCOPES[PRESET_READ_ONLY])
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))

    assert grant is not None
    assert grant.access_preset == PRESET_READ_ONLY
    assert grant.is_depersonalized is True

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_consent_defaults_full_request_to_analytics_preset(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-analytics-default@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    full_scope = " ".join(SUPPORTED_TOKEN_SCOPES)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": full_scope,
            },
        )
        client_id = response.json()["client_id"]
        consent_preview = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": full_scope,
                "state": "preview-state",
                "code_challenge": _pkce_challenge(verifier),
                "code_challenge_method": "S256",
            },
        )
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope=full_scope,
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

    assert consent_preview.status_code == 200
    assert f'value="{PRESET_REPORT_AI}" selected' in consent_preview.text
    assert "report_ai.write" in consent_preview.text
    assert token_response.status_code == 200
    assert token_response.json()["scope"] == " ".join(TOKEN_PRESET_SCOPES[PRESET_REPORT_AI])
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))

    assert grant is not None
    assert grant.access_preset == PRESET_REPORT_AI

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_analytics_default_does_not_expand_narrow_requested_scope(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-narrow-default@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        register_response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": "clients.read",
            },
        )
        client_id = register_response.json()["client_id"]
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope="clients.read",
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

    assert token_response.status_code == 200
    assert token_response.json()["scope"] == "clients.read"
    assert "report_ai.write" not in token_response.json()["scope"]
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))

    assert grant is not None
    assert grant.access_preset == PRESET_REPORT_AI
    assert json.loads(grant.scopes_json) == ["clients.read"]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_consent_allows_explicit_personal_data_mode(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-personal-data@example.com")
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
            privacy_mode="personal_data",
        )
        token_response = await _exchange_authorization_code(
            client,
            raw_code=raw_code,
            client_id=client_id,
            verifier=verifier,
        )

    assert token_response.status_code == 200
    async with storage.get_session_factory()() as session:
        stored_code = await session.scalar(select(OAuthAuthorizationCode))
        grant = await session.scalar(select(OAuthGrant))

    assert stored_code is not None
    assert stored_code.is_depersonalized is False
    assert grant is not None
    assert grant.is_depersonalized is False

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_oauth_tool_call_redacts_personal_fields_by_default(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-redacted-tool@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        client_id = await _register_oauth_client(
            client,
            scope="clients.read pets.read offline_access",
        )
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope="clients.read pets.read offline_access",
            code_challenge=_pkce_challenge(verifier),
        )
        token_response = await _exchange_authorization_code(
            client,
            raw_code=raw_code,
            client_id=client_id,
            verifier=verifier,
        )

    assert token_response.status_code == 200
    raw_access_token = token_response.json()["access_token"]
    _mock_client_lookup_with_personal_fields()
    monkeypatch.setattr(
        auth_request,
        "_get_request_headers",
        lambda: {"authorization": f"Bearer {raw_access_token}"},
    )

    result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    assert result.structured_content["data"]["id"] == 42
    assert result.structured_content["data"]["firstName"] == REDACTED_NAME
    assert result.structured_content["data"]["phone"] == REDACTED_PHONE
    assert result.structured_content["data"]["email"] == REDACTED_EMAIL

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_oauth_tool_call_preserves_personal_fields_when_explicitly_allowed(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-raw-tool@example.com")
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
            privacy_mode="personal_data",
        )
        token_response = await _exchange_authorization_code(
            client,
            raw_code=raw_code,
            client_id=client_id,
            verifier=verifier,
        )

    assert token_response.status_code == 200
    raw_access_token = token_response.json()["access_token"]
    _mock_client_lookup_with_personal_fields()
    monkeypatch.setattr(
        auth_request,
        "_get_request_headers",
        lambda: {"authorization": f"Bearer {raw_access_token}"},
    )

    result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    assert result.structured_content["data"]["firstName"] == "Anna"
    assert result.structured_content["data"]["phone"] == "+7 (916) 123-45-67"
    assert result.structured_content["data"]["email"] == "anna@example.com"

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_legacy_oauth_tool_call_redacts_personal_fields_for_null_privacy_marker(
    tmp_path,
    monkeypatch,
):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-legacy-null-tool@example.com")
    raw_access_token = "vm_oat_legacy_null_privacy"

    async with storage.get_session_factory()() as session:
        account = await session.get(Account, account_id)
        connection = await session.scalar(select(VetmanagerConnection))
        oauth_client = OAuthClient(
            client_id="vm_oc_legacy_null_privacy",
            client_name="ChatGPT",
            redirect_uris_json='["https://chat.openai.com/aip/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]',
            scope="clients.read",
            status="active",
        )
        session.add(oauth_client)
        await session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id=oauth_client.client_id,
            scopes_json='["clients.read"]',
            is_depersonalized=None,
            status="active",
        )
        session.add(grant)
        await session.flush()
        session.add(
            OAuthAccessToken(
                grant_id=grant.id,
                token_prefix=build_token_prefix(raw_access_token),
                token_hash=hash_bearer_token(raw_access_token),
                scope="clients.read",
                resource="https://test.example.com/mcp",
                status="active",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await session.commit()

    _mock_client_lookup_with_personal_fields()
    monkeypatch.setattr(
        auth_request,
        "_get_request_headers",
        lambda: {"authorization": f"Bearer {raw_access_token}"},
    )

    result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    assert result.structured_content["data"]["firstName"] == REDACTED_NAME
    assert result.structured_content["data"]["phone"] == REDACTED_PHONE
    assert result.structured_content["data"]["email"] == REDACTED_EMAIL

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_consent_rejects_full_access_without_confirmation(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-full-confirm@example.com")
    full_scope = " ".join(SUPPORTED_TOKEN_SCOPES)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": full_scope,
            },
        )
        client_id = response.json()["client_id"]
        consent_response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": full_scope,
                "state": "state-full",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
        )
        callback_response = await client.post(
            "/oauth/authorize/consent",
            data={
                "csrf_token": CSRF_RE.search(consent_response.text).group(1),
                "request_state": REQUEST_STATE_RE.search(consent_response.text).group(1),
                "connection_id": CONNECTION_ID_RE.search(consent_response.text).group(1),
                "access_preset": PRESET_FULL_ACCESS,
            },
            follow_redirects=False,
        )

    assert callback_response.status_code == 400
    assert "Full access requires explicit confirmation." in callback_response.text
    async with storage.get_session_factory()() as session:
        assert await session.scalar(select(OAuthAuthorizationCode)) is None

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_consent_rejects_empty_scope_intersection(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="oauth-empty-intersection@example.com")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": "messaging.write",
            },
        )
        client_id = response.json()["client_id"]
        consent_response = await client.get(
            "/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": client_id,
                "redirect_uri": "https://chat.openai.com/aip/callback",
                "resource": "https://test.example.com/mcp",
                "scope": "messaging.write",
                "state": "state-empty",
                "code_challenge": "challenge",
                "code_challenge_method": "S256",
            },
        )
        callback_response = await client.post(
            "/oauth/authorize/consent",
            data={
                "csrf_token": CSRF_RE.search(consent_response.text).group(1),
                "request_state": REQUEST_STATE_RE.search(consent_response.text).group(1),
                "connection_id": CONNECTION_ID_RE.search(consent_response.text).group(1),
                "access_preset": PRESET_READ_ONLY,
            },
            follow_redirects=False,
        )

    assert callback_response.status_code == 400
    assert "Selected access level does not include any requested scopes." in callback_response.text
    async with storage.get_session_factory()() as session:
        assert await session.scalar(select(OAuthAuthorizationCode)) is None

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
        client_id = await _register_oauth_client(
            client,
            scope="clients.read pets.read offline_access",
        )
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope="clients.read pets.read offline_access",
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
                "scope": "clients.read pets.read offline_access",
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
    assert first_payload["scope"] == "clients.read pets.read offline_access"
    assert replay_response.status_code == 400
    assert replay_response.json()["error"] == "invalid_grant"
    assert refresh_response.status_code == 200
    second_payload = refresh_response.json()
    assert second_payload["refresh_token"] != first_payload["refresh_token"]
    assert second_payload["access_token"] != first_payload["access_token"]
    assert second_payload["scope"] == "clients.read pets.read offline_access"
    assert reuse_response.status_code == 400
    assert reuse_response.json()["error"] == "invalid_grant"

    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))
        access_tokens = (await session.execute(select(OAuthAccessToken))).scalars().all()
        refresh_tokens = (await session.execute(select(OAuthRefreshToken))).scalars().all()

    assert grant is not None
    assert json.loads(grant.scopes_json) == ["clients.read", "pets.read"]
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
async def test_oauth_refresh_rejects_legacy_full_access_grant_with_relink_message(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="legacy-full-oauth@example.com")
    raw_refresh_token = "vm_ort_legacy-refresh-token"
    legacy_full_scopes = LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS[0]
    full_scope = " ".join(legacy_full_scopes)

    async with storage.get_session_factory()() as session:
        connection = await session.scalar(select(VetmanagerConnection))
        oauth_client = OAuthClient(
            client_id="vm_oc_legacy_full",
            client_name="ChatGPT",
            redirect_uris_json='["https://chat.openai.com/aip/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]',
            scope=full_scope,
            status="active",
        )
        session.add(oauth_client)
        await session.flush()
        grant = OAuthGrant(
            account_id=account_id,
            vetmanager_connection_id=connection.id,
            client_id=oauth_client.client_id,
            scopes_json=oauth_service._stable_json(list(legacy_full_scopes)),
            access_preset=None,
            status="active",
        )
        session.add(grant)
        await session.flush()
        session.add(
            OAuthRefreshToken(
                grant_id=grant.id,
                token_prefix=build_token_prefix(raw_refresh_token),
                token_hash=hash_bearer_token(raw_refresh_token),
                scope=full_scope,
                resource="https://test.example.com/mcp",
                status="active",
                expires_at=datetime.now(timezone.utc) + timedelta(days=30),
            )
        )
        await session.commit()
        grant_id = grant.id

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": raw_refresh_token,
                "client_id": "vm_oc_legacy_full",
                "resource": "https://test.example.com/mcp",
            },
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_grant"
    assert "Reconnect ChatGPT and choose an access level." in payload["error_description"]
    async with storage.get_session_factory()() as session:
        stored_grant = await session.get(OAuthGrant, grant_id)
        refresh_tokens = (await session.execute(select(OAuthRefreshToken))).scalars().all()

    assert stored_grant.status == "revoked"
    assert stored_grant.revocation_reason == "legacy_full_access_relink_required"
    assert {token.status for token in refresh_tokens} == {"revoked"}

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_oauth_refresh_allows_new_confirmed_full_access_with_legacy_snapshot_scope(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    account_id = await _register_account_with_connection(email="new-full-legacy-snapshot@example.com")
    verifier = "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz"
    legacy_full_scope = " ".join(LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS[0])
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        register_response = await client.post(
            "/oauth/register",
            json={
                "client_name": "ChatGPT",
                "redirect_uris": ["https://chat.openai.com/aip/callback"],
                "scope": legacy_full_scope,
            },
        )
        client_id = register_response.json()["client_id"]
        raw_code = await _authorize_and_consent(
            client,
            client_id=client_id,
            scope=legacy_full_scope,
            code_challenge=_pkce_challenge(verifier),
            access_preset=PRESET_FULL_ACCESS,
            confirm_full_access=True,
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
        refresh_response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": token_response.json()["refresh_token"],
                "client_id": client_id,
                "resource": "https://test.example.com/mcp",
            },
        )

    assert token_response.status_code == 200
    assert refresh_response.status_code == 200
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))

    assert grant is not None
    assert grant.access_preset == PRESET_FULL_ACCESS
    assert grant.status == "active"

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
async def test_account_ui_lists_and_revokes_oauth_grant_family(tmp_path, monkeypatch, caplog):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    reset_service_metrics()
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
            is_depersonalized=True,
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
    with caplog.at_level("INFO"):
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
            page_response = await client.get("/account")
            csrf_token = CSRF_RE.search(page_response.text).group(1)
            revoke_response = await client.post(
                f"/account/oauth-grants/{grant_id}/revoke",
                data={"csrf_token": csrf_token},
            )
            async with storage.get_session_factory()() as session:
                stored_grant = await session.get(OAuthGrant, grant_id)
                assert stored_grant is not None
                stored_grant.status = "revoked"
                access_token = await session.scalar(
                    select(OAuthAccessToken).where(OAuthAccessToken.grant_id == grant_id)
                )
                refresh_token = await session.scalar(
                    select(OAuthRefreshToken).where(OAuthRefreshToken.grant_id == grant_id)
                )
                assert access_token is not None
                assert refresh_token is not None
                access_token.status = "active"
                access_token.revoked_at = None
                refresh_revoked_at = refresh_token.revoked_at
                assert refresh_revoked_at is not None
                await session.commit()
            repeat_revoke_response = await client.post(
                f"/account/oauth-grants/{grant_id}/revoke",
                data={"csrf_token": csrf_token},
            )
            noop_revoke_response = await client.post(
                f"/account/oauth-grants/{grant_id}/revoke",
                data={"csrf_token": csrf_token},
            )

    assert page_response.status_code == 200
    assert 'data-testid="chatgpt-connect-instructions"' in page_response.text
    assert 'data-testid="chatgpt-mcp-url"' in page_response.text
    assert 'data-testid="oauth-grant-list"' in page_response.text
    assert "ChatGPT" in page_response.text
    assert "Custom/legacy" in page_response.text
    assert "Personal data" in page_response.text
    assert "Скрыты" in page_response.text
    assert "clients.read" in page_response.text
    assert f'action="/account/oauth-grants/{grant_id}/revoke"' in page_response.text
    assert revoke_response.status_code == 200
    assert "ChatGPT connection отключена." in revoke_response.text
    assert repeat_revoke_response.status_code == 200
    assert noop_revoke_response.status_code == 200

    async with storage.get_session_factory()() as session:
        stored_grant = await session.get(OAuthGrant, grant_id)
        access_tokens = (await session.execute(select(OAuthAccessToken))).scalars().all()
        refresh_tokens = (await session.execute(select(OAuthRefreshToken))).scalars().all()

    assert stored_grant.status == "revoked"
    assert {token.status for token in access_tokens} == {"revoked"}
    assert {token.status for token in refresh_tokens} == {"revoked"}
    assert [token.revoked_at for token in refresh_tokens] == [refresh_revoked_at]
    assert snapshot_service_metrics()["business_events_total"]["oauth_grant_revoked"] == 1
    assert any(
        getattr(record, "event_name", None) == "oauth_grant_family_repaired"
        and getattr(record, "access_tokens_transitioned", None) is True
        for record in caplog.records
    )
    assert any(
        getattr(record, "event_name", None) == "oauth_grant_revoke_noop"
        for record in caplog.records
    )

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_account_ui_warns_for_legacy_broad_oauth_grant(tmp_path, monkeypatch):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    account_id = await _register_account_with_connection(email="legacy-broad-ui@example.com")

    async def fake_health(*args, **kwargs):
        return "active", "ok"

    monkeypatch.setattr(web, "evaluate_connection_health", fake_health)

    legacy_full_scopes = LEGACY_FULL_ACCESS_SCOPE_SNAPSHOTS[0]
    async with storage.get_session_factory()() as session:
        connection = await session.scalar(select(VetmanagerConnection))
        client = OAuthClient(
            client_id="vm_oc_legacy_broad_ui",
            client_name="ChatGPT",
            redirect_uris_json='["https://chat.openai.com/aip/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]',
            scope=" ".join(legacy_full_scopes),
            status="active",
        )
        session.add(client)
        await session.flush()
        session.add(
            OAuthGrant(
                account_id=account_id,
                vetmanager_connection_id=connection.id,
                client_id=client.client_id,
                scopes_json=oauth_service._stable_json(list(legacy_full_scopes)),
                access_preset=None,
                status="active",
            )
        )
        await session.commit()

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id), path="/")
        page_response = await client.get("/account")

    assert page_response.status_code == 200
    assert "Legacy Full access: reconnect ChatGPT and choose an access level." in page_response.text
    assert "Legacy connection: personal data is hidden now." in page_response.text

    await engine.dispose()
    storage.reset_storage_state()
