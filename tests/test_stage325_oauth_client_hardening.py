"""Regression guards for stage 325 OAuth runtime hardening."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy.exc import IntegrityError

import auth.request as auth_request
import auth.rate_limit as rate_limit
import runtime_auth
from bearer_token_manager import build_token_prefix, hash_bearer_token
from exceptions import AuthError, RateLimitError
from oauth_metadata import get_mcp_resource_url
from storage_models import Account, OAuthAccessToken, OAuthClient, OAuthGrant, VetmanagerConnection


KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
RAW = "vm_oat_stage325"


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "stage325.db")


async def _seed(session_factory, *, client_status="active"):
    async with session_factory() as session:
        account = Account(email="stage325@example.com")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(account_id=account.id, auth_mode="domain_api_key", domain="clinic", status="active")
        connection.set_credentials({"domain": "clinic", "api_key": "key"}, encryption_key=KEY)
        client = OAuthClient(client_id="stage325", client_name="Test", redirect_uris_json="[]", token_endpoint_auth_method="none", grant_types_json="[]", response_types_json="[]", scope="clients.read", status=client_status)
        session.add_all([connection, client])
        await session.flush()
        grant = OAuthGrant(account_id=account.id, vetmanager_connection_id=connection.id, client_id=client.client_id, scopes_json='["clients.read"]', status="active")
        session.add(grant)
        await session.flush()
        token = OAuthAccessToken(grant_id=grant.id, token_prefix=build_token_prefix(RAW), token_hash=hash_bearer_token(RAW), scope="clients.read", resource=get_mcp_resource_url(), status="active", expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        session.add(token)
        await session.commit()


@pytest.mark.asyncio
async def test_disabled_client_rejects_runtime_and_scope_peek(session_factory, monkeypatch):
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", KEY)
    await _seed(session_factory, client_status="disabled")
    monkeypatch.setattr(runtime_auth, "get_session_factory", lambda: session_factory)
    with patch.object(auth_request, "_get_request_headers", return_value={"authorization": f"Bearer {RAW}"}):
        with pytest.raises(AuthError, match="Invalid authorization"):
            await runtime_auth.resolve_runtime_credentials()
    monkeypatch.setattr(runtime_auth, "get_bearer_token", lambda: RAW)
    assert await runtime_auth.peek_runtime_scopes() is None


@pytest.mark.asyncio
async def test_oauth_grant_without_client_is_rejected(session_factory, monkeypatch):
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", KEY)
    await _seed(session_factory)
    async with session_factory() as session:
        client = await session.get(OAuthClient, 1)
        await session.delete(client)
        await session.commit()
    monkeypatch.setattr(runtime_auth, "get_session_factory", lambda: session_factory)
    with patch.object(auth_request, "_get_request_headers", return_value={"authorization": f"Bearer {RAW}"}):
        with pytest.raises(AuthError, match="Invalid authorization"):
            await runtime_auth.resolve_runtime_credentials()


@pytest.mark.asyncio
async def test_oauth_grant_uses_shared_per_token_limit(session_factory, monkeypatch):
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", KEY)
    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "60")
    rate_limit.reset_bearer_rate_limiter()
    await _seed(session_factory)
    monkeypatch.setattr(runtime_auth, "get_session_factory", lambda: session_factory)
    try:
        with patch.object(auth_request, "_get_request_headers", return_value={"authorization": f"Bearer {RAW}"}):
            await runtime_auth.resolve_runtime_credentials()
            with pytest.raises(RateLimitError, match="rate limit exceeded"):
                await runtime_auth.resolve_runtime_credentials()
    finally:
        rate_limit.reset_bearer_rate_limiter()


@pytest.mark.asyncio
async def test_partial_unique_index_allows_disabled_history_but_rejects_second_active(session_factory):
    async with session_factory() as session:
        account = Account(email="index-stage325@example.com")
        session.add(account)
        await session.flush()
        session.add_all([
            VetmanagerConnection(account_id=account.id, auth_mode="domain_api_key", status="disabled"),
            VetmanagerConnection(account_id=account.id, auth_mode="domain_api_key", status="active"),
        ])
        await session.commit()
    async with session_factory() as session:
        session.add(VetmanagerConnection(account_id=1, auth_mode="domain_api_key", status="active"))
        with pytest.raises(IntegrityError):
            await session.commit()


@pytest.mark.parametrize(("site", "path", "expected"), [
    ("https://test.example.com/", "//custom//mcp/", "https://test.example.com/custom/mcp"),
    ("invalid", "custom/mcp", "https://vetmanager-mcp.vromanichev.ru/mcp"),
    ("https://test.example.com", '/mcp\"><img>', "https://test.example.com/mcp"),
])
def test_public_endpoint_normalization_is_shared(monkeypatch, site, path, expected):
    monkeypatch.setenv("SITE_BASE_URL", site)
    monkeypatch.setenv("MCP_PATH", path)
    from landing_page import _resolve_mcp_path, _resolve_site_base_url
    from server import _load_runtime_config
    assert get_mcp_resource_url() == expected
    assert f"{_resolve_site_base_url()}{_resolve_mcp_path()}" == expected
    expected_path = "/custom/mcp" if path == "//custom//mcp/" else "/mcp"
    assert _load_runtime_config()[-1] == expected_path
