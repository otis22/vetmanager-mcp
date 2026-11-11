"""HTTP bearer rejection at the MCP boundary (synthetic credentials only)."""

from datetime import datetime, timedelta, timezone
import asyncio
import logging
import socket

import httpx
import pytest
import uvicorn
from sqlalchemy import select

import storage
import auth.bearer as bearer_runtime
import mcp_bearer_transport as transport_auth
from bearer_token_manager import hash_bearer_token
from exceptions import AuthError
from oauth_challenge import build_oauth_bearer_challenge, oauth_challenge_details
from mcp_bearer_transport import MCPBearerTransportMiddleware
from mcp_transport_observation import MCPTransportObservationMiddleware, wait_handshake_observations
import mcp_transport_observation as observation
from request_context import RequestContextHeaderMiddleware
from server import mcp
from storage_models import (
    Account, OAuthAccessToken, OAuthClient, OAuthGrant, OAuthRefreshToken,
    ServiceBearerToken, VetmanagerConnection,
)


INIT = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
    "protocolVersion": "2025-03-26", "capabilities": {},
    "clientInfo": {"name": "test", "version": "1"}}}
LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


def test_http_and_meta_challenge_share_comma_delimited_parameters(monkeypatch):
    monkeypatch.setenv("SITE_BASE_URL", "https://example.invalid")
    expected = build_oauth_bearer_challenge(scope="clients.read", error="invalid_token")
    assert ', scope="clients.read", error="invalid_token"' in expected
    assert oauth_challenge_details(scope="clients.read", error="invalid_token")[
        "mcp/www_authenticate"] == [expected]


@pytest.mark.asyncio
async def test_invalid_and_expired_bearer_get_http_401_before_mcp(tmp_path, monkeypatch):
    database = tmp_path / "transport-auth.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("SITE_BASE_URL", "https://example.invalid")
    storage.reset_storage_state()
    engine = storage.create_database_engine(f"sqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(storage.Base.metadata.create_all)
    expired = "vm_st_" + "e" * 43
    async with storage.get_session_factory()() as session:
        account = Account(email="transport@example.invalid")
        session.add(account)
        await session.flush()
        session.add(ServiceBearerToken(account_id=account.id, name="expired",
            token_prefix="synthetic", token_hash=hash_bearer_token(expired),
            status="active", expires_at=datetime.now(timezone.utc) - timedelta(days=1)))
        await session.commit()

    async def downstream(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{}'})

    app = MCPBearerTransportMiddleware(downstream)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                base_url="http://testserver") as client:
            for raw_token in ("vm_st_" + "z" * 43, expired):
                for payload in (INIT, LIST):
                    response = await client.post("/mcp", json=payload,
                        headers={"Authorization": f"Bearer {raw_token}"})
                    assert response.status_code == 401
                    challenge = response.headers["www-authenticate"]
                    assert 'error="invalid_token"' in challenge
                    assert 'resource_metadata="https://example.invalid/.well-known/oauth-protected-resource/mcp"' in challenge
                    assert raw_token not in response.text
            for method in ("GET", "DELETE"):
                response = await client.request(method, "/mcp",
                    headers={"Authorization": "Bearer vm_st_" + "z" * 43})
                assert response.status_code == 401
            duplicate = await client.post("/mcp", json=INIT,
                headers=[("Authorization", "Bearer " + expired),
                         ("Authorization", "Bearer vm_st_" + "z" * 43)])
            assert duplicate.status_code == 400
    finally:
        await engine.dispose()
        storage.reset_storage_state()


@pytest.mark.asyncio
async def test_preflight_storage_failure_is_503_without_challenge(monkeypatch):
    async def fail(_token):
        raise RuntimeError("sensitive synthetic exception")

    async def downstream(_scope, _receive, _send):
        raise AssertionError("must not reach MCP")

    monkeypatch.setattr(transport_auth, "_is_invalid", fail)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=MCPBearerTransportMiddleware(downstream)), base_url="http://testserver") as client:
        response = await client.post("/mcp", json=INIT,
            headers={"Authorization": "Bearer vm_st_" + "z" * 43})
    assert response.status_code == 503
    assert response.json() == {"error": "temporarily_unavailable"}
    assert "www-authenticate" not in response.headers
    assert "sensitive" not in response.text


@pytest.mark.asyncio
async def test_slow_preflight_is_bounded_503(monkeypatch):
    async def slow(_token):
        await asyncio.sleep(1)
        return False

    async def downstream(_scope, _receive, _send):
        raise AssertionError("must not reach MCP")

    monkeypatch.setattr(transport_auth, "_is_invalid", slow)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=MCPBearerTransportMiddleware(downstream)), base_url="http://testserver") as client:
        response = await client.post("/mcp", json=INIT,
            headers={"Authorization": "Bearer vm_st_" + "z" * 43})
    assert response.status_code == 503
    assert "www-authenticate" not in response.headers


@pytest.mark.asyncio
async def test_ip_mask_denial_stays_runtime_403_not_transport_401(tmp_path, monkeypatch):
    database = tmp_path / "ip-mask.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    storage.reset_storage_state()
    engine = storage.create_database_engine(f"sqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(storage.Base.metadata.create_all)
    raw_token = "vm_st_" + "i" * 43
    async with storage.get_session_factory()() as session:
        account = Account(email="ip-mask@example.invalid")
        session.add(account)
        await session.flush()
        session.add(ServiceBearerToken(account_id=account.id, name="ip-restricted",
            token_prefix="synthetic", token_hash=hash_bearer_token(raw_token),
            status="active", allowed_ip_mask="203.0.113.7"))
        await session.commit()

    async def downstream(_scope, _receive, send):
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(
                app=MCPBearerTransportMiddleware(downstream)), base_url="http://testserver") as client:
            response = await client.post("/mcp", json=LIST,
                headers={"Authorization": f"Bearer {raw_token}"})
        assert response.status_code == 204
        assert "www-authenticate" not in response.headers
        monkeypatch.setattr(bearer_runtime, "get_request_audit_metadata",
                            lambda: ("198.51.100.1", None))
        async with storage.get_session_factory()() as session:
            with pytest.raises(AuthError) as denied:
                await bearer_runtime.resolve_bearer_auth_context(raw_token, session)
        assert denied.value.status_code == 403
    finally:
        await engine.dispose()
        storage.reset_storage_state()


@pytest.mark.asyncio
async def test_local_http_refresh_then_read_and_service_key(tmp_path, monkeypatch, caplog):
    database = tmp_path / "transport-live.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    monkeypatch.setenv("SITE_BASE_URL", "https://example.invalid")
    monkeypatch.setattr(observation.RUNTIME_LOGGER.logger, "disabled", False)
    storage.reset_storage_state()
    engine = storage.create_database_engine(f"sqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(storage.Base.metadata.create_all)
    now = datetime.now(timezone.utc)
    old_access = "vm_oat_" + "a" * 43
    refresh = "vm_ort_" + "r" * 43
    service = "vm_st_" + "s" * 43
    async with storage.get_session_factory()() as session:
        account = Account(email="transport-live@example.invalid")
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(account_id=account.id, auth_mode="domain_api_key",
            status="active", domain="example.invalid")
        session.add(connection)
        await session.flush()
        client = OAuthClient(client_id="vm_oc_stage454", redirect_uris_json='["https://example.invalid/callback"]',
            token_endpoint_auth_method="none", grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]', scope="clients.read offline_access")
        session.add(client)
        grant = OAuthGrant(account_id=account.id, vetmanager_connection_id=connection.id,
            client_id=client.client_id, scopes_json='["clients.read"]', access_preset="read_only")
        session.add(grant)
        await session.flush()
        resource = "https://example.invalid/mcp"
        session.add_all([
            OAuthAccessToken(grant_id=grant.id, token_prefix="synthetic", token_hash=hash_bearer_token(old_access),
                scope="clients.read offline_access", resource=resource, expires_at=now - timedelta(days=1)),
            OAuthRefreshToken(grant_id=grant.id, token_prefix="synthetic", token_hash=hash_bearer_token(refresh),
                scope="clients.read offline_access", resource=resource, expires_at=now + timedelta(days=1)),
            ServiceBearerToken(account_id=account.id, name="valid", token_prefix="synthetic",
                token_hash=hash_bearer_token(service), status="active"),
        ])
        await session.commit()

    app = RequestContextHeaderMiddleware(MCPTransportObservationMiddleware(
        MCPBearerTransportMiddleware(mcp.http_app(path="/mcp", transport="streamable-http",
            stateless_http=True, json_response=True))))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen()
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False, ws="none"))
    serving = asyncio.create_task(server.serve(sockets=[sock]))
    try:
        for _ in range(100):
            if server.started:
                break
            await asyncio.sleep(.01)
        assert server.started
        with caplog.at_level(logging.INFO):
            async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                headers = {"Accept": "application/json, text/event-stream"}
                expired = await client.post("/mcp", json=LIST,
                    headers={**headers, "Authorization": f"Bearer {old_access}"})
                refreshed = await client.post("/oauth/token", data={"grant_type": "refresh_token",
                    "refresh_token": refresh, "client_id": "vm_oc_stage454", "resource": resource})
                assert refreshed.status_code == 200
                new_access = refreshed.json()["access_token"]
                read = await client.post("/mcp", json=LIST,
                    headers={**headers, "Authorization": f"Bearer {new_access}"})
                permanent = await client.post("/mcp", json=INIT,
                    headers={**headers, "Authorization": f"Bearer {service}"})
                discovery = await client.get("/.well-known/oauth-protected-resource/mcp")
            await wait_handshake_observations()
        assert expired.status_code == 401
        assert 'error="invalid_token"' in expired.headers["www-authenticate"]
        assert (read.status_code, permanent.status_code, discovery.status_code) == (200, 200, 200)
        assert "tools" in read.json()["result"]
        assert "protocolVersion" in permanent.json()["result"]
        assert any(getattr(record, "event_name", None) == "mcp_handshake"
                   and record.http_status == 401 for record in caplog.records)
        async with storage.get_session_factory()() as session:
            access = await session.scalar(select(OAuthAccessToken).where(
                OAuthAccessToken.token_hash == hash_bearer_token(new_access)))
            grant = await session.get(OAuthGrant, access.grant_id)
            grant.status = "revoked"
            await session.commit()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
            revoked_grant = await client.post("/mcp", json=LIST,
                headers={**headers, "Authorization": f"Bearer {new_access}"})
        assert revoked_grant.status_code == 401
        print("stage454 local HTTP: expired=401 challenge=Bearer; refresh=200; read=200 tools-array; service=200 protocolVersion; discovery=200")
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, timeout=5)
        sock.close()
        await engine.dispose()
        storage.reset_storage_state()
