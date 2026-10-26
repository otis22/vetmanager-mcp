"""Stage 440 red guards: token refusals and stale revoked-grant refreshes."""

from datetime import datetime, timedelta, timezone
import json

import fakeredis
import httpx
import pytest
from sqlalchemy import select

import storage
import web_routes_oauth
from bearer_token_manager import build_token_prefix, hash_bearer_token
from server import mcp
from service_metrics import render_prometheus_metrics, reset_service_metrics, snapshot_service_metrics
from shared_metric_counters import COUNTERS_KEY, RedisMetricCounters
from storage_models import OAuthClient, OAuthGrant, OAuthRefreshToken, VetmanagerConnection
from tests.test_stage173_oauth_metadata import _prepare_oauth_db, _register_account_with_connection


RESOURCE = "https://test.example.com/mcp"


def _metric(name: str, labels: str = "") -> int:
    rows = [line for line in render_prometheus_metrics().splitlines()
            if (line.startswith(name + "{") if labels else line.startswith(name + " "))
            and labels in line]
    return int(rows[0].rsplit(" ", 1)[1]) if rows else 0


@pytest.mark.asyncio
async def test_token_refusals_expose_bounded_code_without_secrets(tmp_path, monkeypatch, caplog):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    reset_service_metrics()
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    secret = "vm_ort_stage440_secret_never_log"
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        with caplog.at_level("INFO"):
            bad = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": secret,
                "client_id": "vm_oc_stage440", "resource": RESOURCE,
            })
            code = await client.post("/oauth/token", data={
                "grant_type": "authorization_code", "code": "missing-code",
                "client_id": "vm_oc_stage440", "redirect_uri": "https://example.com/callback",
                "resource": RESOURCE, "code_verifier": "Verifier-1234567890-abcdefghijklmnopqrstuvwxyz",
            })
            unknown = await client.post("/oauth/token", data={
                "grant_type": "attacker\nlabel", "client_id": "vm_oc_stage440\nforged"})

    assert bad.status_code == 400 and bad.json()["error"] == "invalid_grant"
    assert code.status_code == 400 and code.json()["error"] == "invalid_grant"
    assert unknown.status_code == 400 and unknown.json()["error"] == "unsupported_grant_type"
    assert _metric("vetmanager_oauth_token_errors_total", 'error="invalid_grant",grant_type="refresh_token"') == 1
    assert _metric("vetmanager_oauth_token_errors_total", 'error="invalid_grant",grant_type="authorization_code"') == 1
    assert _metric("vetmanager_oauth_token_errors_total", 'error="unsupported_grant_type",grant_type="other"') == 1
    refusals = [r for r in caplog.records if getattr(r, "event_name", None) == "oauth_token_rejected"]
    assert len(refusals) >= 3
    assert any(r.error == "invalid_grant" and r.grant_type == "refresh_token"
               and r.client_id == "vm_oc_stage440" and r.grant_id is None for r in refusals)
    assert all(secret not in str(r.__dict__) and "forged" not in str(r.__dict__) for r in refusals)
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_early_token_refusals_are_counted_without_flood_logs(tmp_path, monkeypatch, caplog):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    reset_service_metrics()
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
                                 base_url="http://testserver") as client:
        with caplog.at_level("INFO"):
            wrong_type = [await client.post("/oauth/token", content=b"x", headers={
                "Content-Type": "application/json"}) for _ in range(3)]
            oversized = await client.post("/oauth/token", content=b"x" * 110000, headers={
                "Content-Type": "application/x-www-form-urlencoded"})
            invalid_utf8 = await client.post("/oauth/token", content=b"\xff", headers={
                "Content-Type": "application/x-www-form-urlencoded"})
    assert [r.status_code for r in wrong_type] == [415, 415, 415]
    assert oversized.status_code == 413 and invalid_utf8.status_code == 500
    assert snapshot_service_metrics()["oauth_token_errors_total"]["invalid_request|other"] == 5
    refusals = [r for r in caplog.records if getattr(r, "event_name", None) == "oauth_token_rejected"]
    assert len(refusals) <= 2
    await engine.dispose()
    storage.reset_storage_state()


def test_oauth_counters_do_not_poison_old_shared_reader():
    redis = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(redis)
    backend.increment("oauth_token_errors_total", "invalid_grant|refresh_token")
    backend.increment("oauth_stale_grant_refresh_total", "")
    assert all(json.loads(field)[0] not in {"oauth_token_errors_total",
                                           "oauth_stale_grant_refresh_total"}
               for field in redis.hgetall(COUNTERS_KEY))
    snapshot = backend.snapshot()
    assert snapshot["oauth_token_errors_total"]["invalid_grant|refresh_token"] == 1
    assert snapshot["oauth_stale_grant_refresh_total"] == 1


async def _seed_revoked_grant(account_id: int, *, client_id: str, token: str,
                              with_heir: bool) -> int:
    async with storage.get_session_factory()() as session:
        connection = await session.scalar(select(VetmanagerConnection).where(
            VetmanagerConnection.account_id == account_id))
        session.add(OAuthClient(
            client_id=client_id, client_name="Stage 440", status="active",
            redirect_uris_json='["https://example.com/callback"]',
            token_endpoint_auth_method="none",
            grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]', scope="clients.read offline_access",
        ))
        old = OAuthGrant(
            account_id=account_id, vetmanager_connection_id=connection.id,
            client_id=client_id, scopes_json='["clients.read"]', status="revoked")
        session.add(old)
        await session.flush()
        if with_heir:
            session.add(OAuthGrant(
                account_id=account_id, vetmanager_connection_id=connection.id,
                client_id=client_id, scopes_json='["clients.read"]', status="active"))
        session.add(OAuthRefreshToken(
            grant_id=old.id, token_prefix=build_token_prefix(token),
            token_hash=hash_bearer_token(token), scope="clients.read offline_access",
            resource=RESOURCE, status="revoked",
            expires_at=datetime.now(timezone.utc) + timedelta(days=10)))
        await session.commit()
        return old.id


@pytest.mark.asyncio
async def test_stale_marker_requires_heir_and_is_daily_per_account(tmp_path, monkeypatch, caplog):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    reset_service_metrics()
    account_id = await _register_account_with_connection("stage440@example.com")
    old_id = await _seed_revoked_grant(
        account_id, client_id="vm_oc_stage440_a", token="vm_ort_stage440_a", with_heir=True)
    await _seed_revoked_grant(
        account_id, client_id="vm_oc_stage440_b", token="vm_ort_stage440_b", with_heir=False)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        with caplog.at_level("INFO"):
            no_heir = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_b",
                "client_id": "vm_oc_stage440_b", "resource": RESOURCE})
            assert _metric("vetmanager_oauth_stale_grant_refresh_total") == 0
            wrong_binding = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_a",
                "client_id": "vm_oc_stage440_a", "resource": "https://wrong.example/mcp"})
            assert _metric("vetmanager_oauth_stale_grant_refresh_total") == 0
            first = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_a",
                "client_id": "vm_oc_stage440_a", "resource": RESOURCE})
            repeated = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_a",
                "client_id": "vm_oc_stage440_a", "resource": RESOURCE})
    assert [r.status_code for r in (no_heir, first, repeated)] == [400, 400, 400]
    assert wrong_binding.status_code == 400
    assert wrong_binding.json() == {"error": "invalid_grant", "error_description": "Refresh token binding mismatch."}
    assert all(r.json()["error"] == "invalid_grant" for r in (no_heir, first, repeated))
    assert _metric("vetmanager_oauth_stale_grant_refresh_total") == 1
    assert any(getattr(r, "event_name", None) == "oauth_token_rejected"
               and r.grant_id == old_id for r in caplog.records)
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_stale_signal_failure_preserves_original_denial(tmp_path, monkeypatch, caplog):
    engine = await _prepare_oauth_db(tmp_path, monkeypatch)
    reset_service_metrics()
    account_id = await _register_account_with_connection("stage440-failure@example.com")
    await _seed_revoked_grant(
        account_id, client_id="vm_oc_stage440_fail",
        token="vm_ort_stage440_fail", with_heir=True)

    async def broken_claim(*_args, **_kwargs):
        raise RuntimeError("marker unavailable")

    monkeypatch.setattr(web_routes_oauth, "claim_stale_oauth_refresh", broken_claim)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        with caplog.at_level("INFO"):
            response = await client.post("/oauth/token", data={
                "grant_type": "refresh_token", "refresh_token": "vm_ort_stage440_fail",
                "client_id": "vm_oc_stage440_fail", "resource": RESOURCE})
    assert response.status_code == 400
    assert response.json() == {"error": "invalid_grant", "error_description": "Grant is not active."}
    assert _metric("vetmanager_oauth_stale_grant_refresh_total") == 0
    assert _metric("vetmanager_oauth_token_errors_total", 'error="invalid_grant",grant_type="refresh_token"') == 1
    assert any(getattr(r, "event_name", None) == "oauth_stale_grant_refresh_failed"
               for r in caplog.records)
    await engine.dispose()
    storage.reset_storage_state()
