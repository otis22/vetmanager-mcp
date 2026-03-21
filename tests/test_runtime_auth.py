"""Unit tests for stage 22.3 runtime credentials resolution."""

from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

import request_credentials
import runtime_auth
from bearer_token_manager import generate_bearer_token
from exceptions import AuthError
from storage import Base, create_database_engine
from storage_models import Account, ServiceBearerToken, VetmanagerConnection
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'runtime-auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_prefers_bearer_context(tmp_path: Path, monkeypatch):
    """Bearer-based account context should become the primary runtime source."""
    session_factory = await _make_session_factory(tmp_path)
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
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            resolved = await runtime_auth.resolve_runtime_credentials()

    assert resolved.source == "bearer"
    assert resolved.domain == "bearer-clinic"
    assert resolved.api_key == "bearer-key"
    assert resolved.vetmanager_auth.auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY


@pytest.mark.asyncio
async def test_resolve_runtime_credentials_requires_bearer_header():
    """Runtime auth is bearer-only once legacy header fallback is removed."""
    with patch.object(request_credentials, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError, match="Missing Authorization"):
            await runtime_auth.resolve_runtime_credentials()


@pytest.mark.asyncio
async def test_vetmanager_client_uses_bearer_runtime_credentials(tmp_path: Path, monkeypatch):
    """Client should lazily resolve credentials from bearer account context."""
    import httpx
    import respx
    from vetmanager_client import VetmanagerClient

    session_factory = await _make_session_factory(tmp_path)
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
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
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
