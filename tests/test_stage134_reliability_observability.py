"""Stage 134 reliability and observability hardening regressions."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp import FastMCP
from sqlalchemy import select
from starlette.exceptions import HTTPException

import host_resolver
import server
import storage
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED, add_token_usage_log, commit_token_usage_log
from bearer_token_manager import generate_bearer_token
from exceptions import HostResolutionError
from host_resolver import reset_billing_resolver, resolve_vetmanager_host
from service_metrics import reset_service_metrics, snapshot_service_metrics
from storage import Base, create_database_engine
from storage_models import Account, ServiceBearerToken, TokenUsageLog
from web import MAX_FORM_PAYLOAD_BYTES, _observed_custom_route
from web_security import reset_web_security_state


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
DOMAIN = "stage134clinic"
BILLING_URL = f"https://billing-api.vetmanager.cloud/host/{DOMAIN}"
RESOLVED_HOST = f"https://{DOMAIN}.vetmanager.cloud"


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "stage134-web.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()

    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _seed_token(session):
    account = Account(email="stage134@example.com", status="active")
    session.add(account)
    await session.flush()
    token = ServiceBearerToken(account_id=account.id, name="Stage 134 token")
    token.set_raw_token(generate_bearer_token())
    session.add(token)
    await session.flush()
    return account, token


async def _noop_async() -> None:
    return None


@pytest.mark.asyncio
async def test_graceful_shutdown_closes_rate_limit_backend(monkeypatch):
    calls: list[str] = []

    async def fake_shutdown_rate_limit_backend() -> None:
        calls.append("rate_limit")

    monkeypatch.setattr(server, "reset_shared_http_client", _noop_async)
    monkeypatch.setattr(server, "reset_breakers", _noop_async)
    monkeypatch.setattr(server, "reset_billing_resolver", _noop_async)
    monkeypatch.setattr(
        server,
        "shutdown_rate_limit_backend",
        fake_shutdown_rate_limit_backend,
        raising=False,
    )

    await server._graceful_shutdown()

    assert calls == ["rate_limit"]


@pytest.mark.asyncio
async def test_graceful_shutdown_logs_rate_limit_backend_failure(monkeypatch, caplog):
    async def failing_shutdown_rate_limit_backend() -> None:
        raise RuntimeError("redis close failed")

    monkeypatch.setattr(server, "reset_shared_http_client", _noop_async)
    monkeypatch.setattr(server, "reset_breakers", _noop_async)
    monkeypatch.setattr(server, "reset_billing_resolver", _noop_async)
    monkeypatch.setattr(
        server,
        "shutdown_rate_limit_backend",
        failing_shutdown_rate_limit_backend,
        raising=False,
    )

    caplog.set_level(logging.WARNING, logger="vetmanager.runtime")
    await server._graceful_shutdown()

    assert any(
        record.__dict__.get("event_name") == "shutdown_error"
        and record.__dict__.get("step") == "shutdown_rate_limit_backend"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_token_audit_commit_helper_logs_only_after_successful_commit(
    sqlite_session_factory_builder,
    tmp_path: Path,
    caplog,
):
    factory = await sqlite_session_factory_builder(tmp_path / "audit-commit.db")
    caplog.set_level(logging.INFO, logger="vetmanager.audit")

    async with factory() as session:
        _account, token = await _seed_token(session)
        audit_event = add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            details={"reason": "succeeded"},
        )

        assert not [
            r for r in caplog.records
            if r.__dict__.get("event_name") == "token_audit_log_committed"
        ]

        await commit_token_usage_log(session, audit_event)

    committed_records = [
        r for r in caplog.records
        if r.__dict__.get("event_name") == "token_audit_log_committed"
    ]
    assert len(committed_records) == 1
    assert committed_records[0].__dict__["token_event_type"] == TOKEN_EVENT_AUTH_SUCCEEDED
    assert committed_records[0].__dict__["bearer_token_id"] == token.id


@pytest.mark.asyncio
async def test_token_audit_commit_failure_does_not_emit_committed_log(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    factory = await sqlite_session_factory_builder(tmp_path / "audit-rollback.db")
    caplog.set_level(logging.INFO, logger="vetmanager.audit")

    async with factory() as session:
        _account, token = await _seed_token(session)
        audit_event = add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            details={"reason": "succeeded"},
        )

        async def fail_commit() -> None:
            raise RuntimeError("commit failed")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit failed"):
            await commit_token_usage_log(session, audit_event)

    assert not [
        r for r in caplog.records
        if r.__dict__.get("event_name") == "token_audit_log_committed"
    ]


@pytest.mark.asyncio
async def test_token_audit_enriches_only_request_and_correlation_ids(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "audit-context.db")
    monkeypatch.setattr(
        "auth_audit.get_current_request_context",
        lambda: {
            "request_id": "req-134",
            "correlation_id": "corr-134",
            "api_key": "must-not-leak",
            "email": "must-not-leak@example.com",
        },
    )

    async with factory() as session:
        _account, token = await _seed_token(session)
        audit_event = add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            details={"reason": "succeeded"},
        )
        await commit_token_usage_log(session, audit_event)

    async with factory() as session:
        row = await session.scalar(select(TokenUsageLog))

    details = json.loads(row.details_json)
    assert details["request_id"] == "req-134"
    assert details["correlation_id"] == "corr-134"
    assert "api_key" not in details
    assert "email" not in details
    assert "must-not-leak" not in row.details_json


@pytest.mark.asyncio
async def test_oversized_form_response_has_correlation_headers_and_metrics():
    reset_service_metrics()
    app = server.mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    oversized_body = "x=" + "a" * (MAX_FORM_PAYLOAD_BYTES + 1)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/register",
            content=oversized_body,
            headers={"content-type": "application/x-www-form-urlencoded"},
        )

    assert response.status_code == 413
    assert response.headers["x-request-id"]
    assert response.headers["x-correlation-id"] == response.headers["x-request-id"]
    assert snapshot_service_metrics()["http_requests_total"]["/register|POST|413"] == 1


@pytest.mark.asyncio
async def test_generic_custom_route_exception_is_logged_and_metered(caplog):
    reset_service_metrics()
    test_mcp = FastMCP(name="stage134-test")

    @_observed_custom_route(test_mcp, "/boom", methods=["GET"])
    async def boom(request):
        raise RuntimeError("boom")

    app = test_mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    caplog.set_level(logging.ERROR, logger="vetmanager.runtime")
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/boom")

    assert response.status_code == 500
    assert snapshot_service_metrics()["http_requests_total"]["/boom|GET|500"] == 1
    assert any(
        record.__dict__.get("event_name") == "custom_route_error"
        and record.__dict__.get("route") == "/boom"
        and record.__dict__.get("method") == "GET"
        and record.__dict__.get("status_code") == 500
        for record in caplog.records
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"Authorization": "Bearer wrong"},
    ],
)
async def test_metrics_unauthorized_logs_security_event_and_metric(
    tmp_path: Path,
    monkeypatch,
    caplog,
    headers: dict[str, str],
):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    reset_service_metrics()
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    app = server.mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)

    caplog.set_level(logging.WARNING, logger="vetmanager.security")
    request_headers = {"X-Request-ID": "req-metrics", **headers}
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/metrics",
            headers=request_headers,
        )

    assert response.status_code == 403
    assert snapshot_service_metrics()["auth_failures_total"]["metrics|invalid_token"] == 1
    assert any(
        record.__dict__.get("event_name") == "metrics_auth_failed"
        and record.__dict__.get("request_id") == "req-metrics"
        and record.__dict__.get("correlation_id") == "req-metrics"
        for record in caplog.records
    )

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_typed_http_exception_keeps_status_code_metric():
    reset_service_metrics()
    test_mcp = FastMCP(name="stage134-http-exception-test")

    @_observed_custom_route(test_mcp, "/missing", methods=["GET"])
    async def missing(request):
        raise HTTPException(status_code=404)

    app = test_mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/missing")

    assert response.status_code == 404
    metrics = snapshot_service_metrics()["http_requests_total"]
    assert metrics["/missing|GET|404"] == 1
    assert "/missing|GET|500" not in metrics


def test_log_startup_aborted_uses_runtime_logger(caplog):
    caplog.set_level(logging.CRITICAL, logger="vetmanager.runtime")

    server._log_startup_aborted(
        RuntimeError("missing secret"),
        step="validate_required_secrets",
    )

    assert any(
        record.__dict__.get("event_name") == "startup_aborted"
        and record.__dict__.get("step") == "validate_required_secrets"
        and "missing secret" in record.getMessage()
        for record in caplog.records
    )


def test_run_startup_step_logs_step_and_reraises(caplog):
    caplog.set_level(logging.CRITICAL, logger="vetmanager.runtime")

    def _fail():
        raise RuntimeError("storage unavailable")

    with pytest.raises(RuntimeError, match="storage unavailable"):
        server._run_startup_step("initialize_storage", _fail)

    assert any(
        record.__dict__.get("event_name") == "startup_aborted"
        and record.__dict__.get("step") == "initialize_storage"
        for record in caplog.records
    )


def test_run_startup_step_does_not_log_system_exit(caplog):
    caplog.set_level(logging.CRITICAL, logger="vetmanager.runtime")

    def _exit():
        raise SystemExit(0)

    with pytest.raises(SystemExit):
        server._run_startup_step("mcp_run", _exit)

    assert not any(
        record.__dict__.get("event_name") == "startup_aborted"
        for record in caplog.records
    )


@pytest.mark.asyncio
@respx.mock
async def test_resolve_host_coalesces_concurrent_cold_cache_calls():
    await reset_billing_resolver()
    route = respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": RESOLVED_HOST}})
    )

    results = await asyncio.gather(
        *(resolve_vetmanager_host(DOMAIN, max_retries=0) for _ in range(5))
    )

    assert results == [RESOLVED_HOST] * 5
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_resolve_host_coalesced_exception_propagates_and_clears_inflight():
    await reset_billing_resolver()
    route = respx.get(BILLING_URL).mock(return_value=httpx.Response(500))

    results = await asyncio.gather(
        *(resolve_vetmanager_host(DOMAIN, max_retries=0) for _ in range(3)),
        return_exceptions=True,
    )

    assert all(isinstance(result, HostResolutionError) for result in results)
    assert route.call_count == 1

    with pytest.raises(HostResolutionError):
        await resolve_vetmanager_host(DOMAIN, max_retries=0)
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_resolve_host_follower_cancellation_does_not_cancel_leader():
    await reset_billing_resolver()
    async def slow_success(request):
        await asyncio.sleep(0.05)
        return httpx.Response(200, json={"data": {"url": RESOLVED_HOST}})

    route = respx.get(BILLING_URL).mock(side_effect=slow_success)
    leader = asyncio.create_task(resolve_vetmanager_host(DOMAIN, max_retries=0))
    follower = asyncio.create_task(resolve_vetmanager_host(DOMAIN, max_retries=0))
    follower.cancel()

    with pytest.raises(asyncio.CancelledError):
        await follower

    assert await leader == RESOLVED_HOST
    assert route.call_count == 1


@pytest.mark.asyncio
async def test_resolve_host_leader_cancellation_propagates_and_clears_inflight(
    monkeypatch,
):
    await reset_billing_resolver()
    started = asyncio.Event()

    async def never_finishes(domain: str, *, max_retries: int) -> str:
        started.set()
        await asyncio.Future()
        return RESOLVED_HOST

    monkeypatch.setattr(
        host_resolver,
        "_resolve_vetmanager_host_uncached",
        never_finishes,
    )

    first = asyncio.create_task(resolve_vetmanager_host(DOMAIN, max_retries=0))
    await started.wait()
    second = asyncio.create_task(resolve_vetmanager_host(DOMAIN, max_retries=0))
    await asyncio.sleep(0)

    loop = asyncio.get_running_loop()
    inflight = host_resolver._inflight_resolutions_by_loop[loop][DOMAIN]
    inflight.cancel()

    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(asyncio.CancelledError):
        await second
    assert DOMAIN not in host_resolver._inflight_resolutions_by_loop.get(loop, {})

    async def succeeds(domain: str, *, max_retries: int) -> str:
        return RESOLVED_HOST

    monkeypatch.setattr(
        host_resolver,
        "_resolve_vetmanager_host_uncached",
        succeeds,
    )
    assert await resolve_vetmanager_host(DOMAIN, max_retries=0) == RESOLVED_HOST
