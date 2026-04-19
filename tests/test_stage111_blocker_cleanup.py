"""Stage 111: blocker cleanup + metric gaps — F1, F3, F5, F6.

Regressions:
- F1: `/metrics` endpoint auth gate via METRICS_AUTH_TOKEN.
- F3: composite index on `token_usage_logs(event_type, event_at)`.
- F5: login rate-limit emits `record_auth_failure(source="web_login", reason="rate_limited")`.
- F6: `record_business_event` logs ERROR on unknown event_name (was silent drop).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

import httpx
import pytest
from sqlalchemy import inspect

import storage
from server import mcp
from service_metrics import (
    record_business_event,
    reset_service_metrics,
    snapshot_service_metrics,
)
from storage import Base, create_database_engine
from web_security import reset_web_security_state
from web_auth import register_account

CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "stage111.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


async def _post_with_csrf(
    client: httpx.AsyncClient,
    path: str,
    data: dict[str, str],
) -> httpx.Response:
    page = await client.get(path)
    match = CSRF_RE.search(page.text)
    assert match is not None
    request_data = dict(data)
    request_data["csrf_token"] = match.group(1)
    return await client.post(path, data=request_data)


# ── F1: /metrics auth gate ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_metrics_open_when_auth_token_env_missing(
    tmp_path: Path, monkeypatch
):
    """Backward-compat: without METRICS_AUTH_TOKEN env, /metrics is open."""
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.delenv("METRICS_AUTH_TOKEN", raising=False)

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "vetmanager_" in response.text
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_returns_403_when_token_set_and_no_auth_header(
    tmp_path: Path, monkeypatch
):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 403
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_returns_200_when_token_matches(tmp_path: Path, monkeypatch):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-metrics-token"},
        )

    assert response.status_code == 200
    assert "vetmanager_" in response.text
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_returns_403_when_token_mismatches(tmp_path: Path, monkeypatch):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer wrong-token"},
        )

    assert response.status_code == 403
    await engine.dispose()
    storage.reset_storage_state()


# ── F3: composite index on token_usage_logs ────────────────────────────────


@pytest.mark.asyncio
async def test_token_usage_logs_composite_index_present(tmp_path: Path, monkeypatch):
    """`create_all` must include the (event_type, event_at) index (stage 111)."""
    database_path = tmp_path / "index-check.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _collect_indexes(sync_conn):
            inspector = inspect(sync_conn)
            return {idx["name"] for idx in inspector.get_indexes("token_usage_logs")}

        indexes = await conn.run_sync(_collect_indexes)

    assert "ix_token_usage_logs_event_type_event_at" in indexes, (
        f"Expected composite index missing. Present: {indexes}"
    )
    await engine.dispose()


# ── F5: login rate-limit records auth failure ──────────────────────────────


@pytest.mark.asyncio
async def test_login_rate_limit_records_auth_failure(tmp_path: Path, monkeypatch):
    reset_service_metrics()
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    # Tight limits to trigger 429 with few requests
    monkeypatch.setenv("WEB_LOGIN_RATE_LIMIT_ATTEMPTS", "1")
    monkeypatch.setenv("WEB_LOGIN_RATE_LIMIT_WINDOW_SECONDS", "60")

    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="bruteforce@example.com",
            password="Correct-Horse-Bat1",
        )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # First: 401 (wrong pwd); Second: 429 (rate-limited)
        first = await _post_with_csrf(
            client, "/login",
            data={"email": "bruteforce@example.com", "password": "wrong-pass"},
        )
        second = await _post_with_csrf(
            client, "/login",
            data={"email": "bruteforce@example.com", "password": "wrong-pass"},
        )

    assert first.status_code == 401
    assert second.status_code == 429

    snap = snapshot_service_metrics()
    key = "web_login|rate_limited"
    assert snap["auth_failures_total"].get(key, 0) >= 1, (
        f"Expected 'web_login|rate_limited' in auth_failures_total, got: "
        f"{snap['auth_failures_total']}"
    )

    await engine.dispose()
    storage.reset_storage_state()


# ── F6: record_business_event unknown event logs ERROR ─────────────────────


def test_record_business_event_unknown_logs_error(caplog):
    """Unknown event_name must log ERROR (not silent-drop) and not increment counter."""
    reset_service_metrics()
    with caplog.at_level(logging.ERROR):
        record_business_event("accont_registered")  # typo

    # Counter must NOT be incremented
    snap = snapshot_service_metrics()
    assert snap["business_events_total"].get("accont_registered", 0) == 0

    # ERROR log must be emitted with the dropped name surfaced
    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(error_records) >= 1, "Expected ERROR log for unknown event_name"
    messages = [r.getMessage() for r in error_records]
    assert any("unknown" in m.lower() or "dropped" in m.lower() for m in messages), (
        f"Expected 'unknown' or 'dropped' in ERROR message, got: {messages}"
    )


def test_record_business_event_known_still_increments(caplog):
    """Regression: known event_name still increments, no ERROR log."""
    reset_service_metrics()
    with caplog.at_level(logging.ERROR):
        record_business_event("account_registered")

    snap = snapshot_service_metrics()
    assert snap["business_events_total"].get("account_registered", 0) == 1

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not error_records, f"Did not expect ERROR logs, got: {[r.getMessage() for r in error_records]}"
