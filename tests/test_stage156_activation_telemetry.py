"""Stage 156 — activation telemetry and no-traffic alert coverage."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

import activation_telemetry
import storage
import web_routes_system
from activation_telemetry import reset_activation_telemetry_state, scan_activation_telemetry
from server import mcp
from service_metrics import (
    render_prometheus_metrics,
    set_account_last_request_age_hours,
    set_activation_funnel_accounts,
    snapshot_service_metrics,
)
from storage import Base, create_database_engine
from storage_models import (
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TOKEN_STATUS_DISABLED,
    TOKEN_STATUS_EXPIRED,
    TOKEN_STATUS_REVOKED,
    VetmanagerConnection,
)
from web_security import reset_web_security_state


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "stage156.db")


@pytest.fixture(autouse=True)
def _reset_activation_state():
    reset_activation_telemetry_state()
    yield
    reset_activation_telemetry_state()


async def _prepare_web_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    database_path = tmp_path / "stage156-web.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-web-session-secret")
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    storage.reset_storage_state()
    reset_web_security_state()
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


_TOKEN_COUNTER = {"n": 0}


async def _make_account_with_token(
    session,
    *,
    email: str,
    created_at: datetime,
    last_used_at: datetime | None = None,
    token_status: str = TOKEN_STATUS_ACTIVE,
    connection_status: str | None = "active",
    expires_at: datetime | None = None,
) -> tuple[Account, ServiceBearerToken]:
    account = Account(email=email, status="active", created_at=created_at, updated_at=created_at)
    session.add(account)
    await session.flush()

    if connection_status is not None:
        session.add(
            VetmanagerConnection(
                account_id=account.id,
                auth_mode="domain_api_key",
                status=connection_status,
                domain="clinic-a",
                created_at=created_at,
                updated_at=created_at,
            )
        )

    _TOKEN_COUNTER["n"] += 1
    suffix = _TOKEN_COUNTER["n"]
    token = ServiceBearerToken(
        account_id=account.id,
        name=f"token-{suffix}",
        token_prefix=f"sbt_stage156_{suffix:04d}",
        token_hash=f"stage156_hash_{suffix:04d}_" + "x" * 40,
        status=token_status,
        created_at=created_at,
        expires_at=expires_at,
        last_used_at=last_used_at,
    )
    session.add(token)
    await session.commit()
    await session.refresh(account)
    await session.refresh(token)
    return account, token


def test_account_last_request_age_metric_renders_prometheus_series() -> None:
    set_account_last_request_age_hours({42: 25.5})
    set_activation_funnel_accounts({
        "registered": 3,
        "ready_for_mcp": 2,
        "unexpected_dynamic_stage": 99,
    })

    snapshot = snapshot_service_metrics()
    metrics_text = render_prometheus_metrics()

    assert snapshot["account_last_request_age_hours"] == {"42": 25.5}
    assert snapshot["activation_funnel_accounts"] == {
        "connected": 0,
        "first_mcp_request": 0,
        "integration_saved": 0,
        "new_registered": 0,
        "ready_for_mcp": 2,
        "registered": 3,
        "token_copied": 0,
        "token_issued": 0,
        "with_active_tokens": 0,
        "with_recent_usage_7d": 0,
    }
    assert "# TYPE vetmanager_account_last_request_age_hours gauge" in metrics_text
    assert 'vetmanager_account_last_request_age_hours{account_id="42"} 25.5' in metrics_text
    assert "# TYPE vetmanager_activation_funnel_accounts gauge" in metrics_text
    assert 'vetmanager_activation_funnel_accounts{stage="connected"} 0' in metrics_text
    assert 'vetmanager_activation_funnel_accounts{stage="registered"} 3' in metrics_text
    assert 'vetmanager_activation_funnel_accounts{stage="ready_for_mcp"} 2' in metrics_text
    assert "unexpected_dynamic_stage" not in metrics_text


@pytest.mark.asyncio
async def test_scan_uses_latest_successful_token_request_age(session_factory):
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account, _token = await _make_account_with_token(
            session,
            email="active@example.com",
            created_at=now - timedelta(days=10),
            last_used_at=now - timedelta(hours=25, minutes=30),
        )

        emitted = await scan_activation_telemetry(session, now=now)

    snapshot = snapshot_service_metrics()
    assert emitted == 1
    assert snapshot["account_last_request_age_hours"] == {str(account.id): 25.5}


@pytest.mark.asyncio
async def test_scan_never_used_token_uses_earliest_live_token_created_at(
    session_factory,
    caplog,
):
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account, _old = await _make_account_with_token(
            session,
            email="never-used@example.com",
            created_at=now - timedelta(hours=80),
        )
        _new_account, new_token = await _make_account_with_token(
            session,
            email="other@example.com",
            created_at=now - timedelta(hours=10),
        )
        new_token.account_id = account.id
        await session.commit()

        caplog.set_level(logging.WARNING, logger="vetmanager.runtime")
        emitted = await scan_activation_telemetry(session, now=now)

    record = next(
        r for r in caplog.records
        if getattr(r, "event_name", None) == "account_traffic_silent"
        and getattr(r, "account_id", None) == account.id
        and getattr(r, "threshold_hours", None) == 72
    )
    assert emitted == 2
    assert snapshot_service_metrics()["account_last_request_age_hours"][str(account.id)] == 80.0
    assert getattr(record, "last_request_at_utc") is None
    assert getattr(record, "ever_used") is False
    assert getattr(record, "age_anchor") == "token_created_at"


@pytest.mark.asyncio
async def test_scan_filters_non_live_accounts_tokens_and_connections(session_factory):
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        live, _ = await _make_account_with_token(
            session,
            email="live@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
        )
        await _make_account_with_token(
            session,
            email="revoked@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
            token_status=TOKEN_STATUS_REVOKED,
        )
        await _make_account_with_token(
            session,
            email="expired@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
            token_status=TOKEN_STATUS_EXPIRED,
        )
        await _make_account_with_token(
            session,
            email="disabled-token@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
            token_status=TOKEN_STATUS_DISABLED,
        )
        await _make_account_with_token(
            session,
            email="expired-by-time@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
            expires_at=now - timedelta(seconds=1),
        )
        await _make_account_with_token(
            session,
            email="no-connection@example.com",
            created_at=now - timedelta(days=3),
            last_used_at=now - timedelta(hours=30),
            connection_status=None,
        )

        await scan_activation_telemetry(session, now=now)

    assert snapshot_service_metrics()["account_last_request_age_hours"] == {str(live.id): 30.0}
    assert snapshot_service_metrics()["activation_funnel_accounts"] == {
        "connected": 5,
        "first_mcp_request": 6,
        "integration_saved": 5,
        "new_registered": 6,
        "ready_for_mcp": 1,
        "registered": 6,
        "token_copied": 0,
        "token_issued": 6,
        "with_active_tokens": 2,
        "with_recent_usage_7d": 1,
    }


@pytest.mark.asyncio
async def test_scan_deduplicates_threshold_logs_until_traffic_resumes(session_factory, caplog):
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    reset_activation_telemetry_state()

    async with session_factory() as session:
        account, token = await _make_account_with_token(
            session,
            email="dedup@example.com",
            created_at=now - timedelta(days=5),
            last_used_at=now - timedelta(hours=80),
        )
        caplog.set_level(logging.WARNING, logger="vetmanager.runtime")

        first = await scan_activation_telemetry(session, now=now)
        second = await scan_activation_telemetry(session, now=now + timedelta(minutes=5))
        token.last_used_at = now + timedelta(minutes=10)
        await session.commit()
        resumed = await scan_activation_telemetry(session, now=now + timedelta(minutes=11))
        token.last_used_at = now - timedelta(hours=80)
        await session.commit()
        third = await scan_activation_telemetry(session, now=now + timedelta(minutes=20))

    records = [
        r for r in caplog.records
        if getattr(r, "event_name", None) == "account_traffic_silent"
        and getattr(r, "account_id", None) == account.id
    ]
    assert first == 2
    assert second == 0
    assert resumed == 0
    assert third == 2
    assert [getattr(r, "threshold_hours") for r in records] == [24, 72, 24, 72]


@pytest.mark.asyncio
async def test_metrics_endpoint_runs_activation_scan_after_auth(tmp_path: Path, monkeypatch):
    now = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    async with storage.get_session_factory()() as session:
        account, _ = await _make_account_with_token(
            session,
            email="metrics@example.com",
            created_at=now - timedelta(days=5),
            last_used_at=now - timedelta(hours=25),
        )

    async def fake_scan(session, *, now=None):
        set_account_last_request_age_hours({account.id: 25.0})
        set_activation_funnel_accounts({"registered": 1, "ready_for_mcp": 1})
        return 1

    monkeypatch.setattr(activation_telemetry, "scan_activation_telemetry", fake_scan)

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        forbidden = await client.get("/metrics")
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-metrics-token"},
        )

    assert forbidden.status_code == 403
    assert response.status_code == 200
    assert f'vetmanager_account_last_request_age_hours{{account_id="{account.id}"}} 25.0' in response.text
    assert 'vetmanager_activation_funnel_accounts{stage="connected"} 0' in response.text
    assert 'vetmanager_activation_funnel_accounts{stage="registered"} 1' in response.text
    assert 'vetmanager_activation_funnel_accounts{stage="ready_for_mcp"} 1' in response.text
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_endpoint_skips_activation_scan_when_auth_is_unset(
    tmp_path: Path,
    monkeypatch,
):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.delenv("METRICS_AUTH_TOKEN", raising=False)
    called = False

    async def unexpected_scan(session, *, now=None):
        nonlocal called
        called = True
        raise AssertionError("activation scan must require explicit metrics auth")

    monkeypatch.setattr(activation_telemetry, "scan_activation_telemetry", unexpected_scan)

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/metrics")

    assert response.status_code == 200
    assert "vetmanager_http_requests_total" in response.text
    assert called is False
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_endpoint_keeps_serving_when_activation_scan_fails(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")

    async def broken_scan(session, *, now=None):
        raise RuntimeError("scan failed")

    monkeypatch.setattr(activation_telemetry, "scan_activation_telemetry", broken_scan)
    caplog.set_level(logging.WARNING, logger="vetmanager.runtime")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-metrics-token"},
        )

    assert response.status_code == 200
    assert "vetmanager_http_requests_total" in response.text
    assert any(
        getattr(record, "event_name", None) == "activation_telemetry_scan_failed"
        for record in caplog.records
    )
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_metrics_endpoint_bounds_activation_scan_timeout(
    tmp_path: Path,
    monkeypatch,
    caplog,
):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "secret-metrics-token")
    monkeypatch.setattr(web_routes_system, "ACTIVATION_TELEMETRY_SCAN_TIMEOUT_SECONDS", 0.01)

    async def slow_scan(session, *, now=None):
        await asyncio.sleep(60)
    monkeypatch.setattr(activation_telemetry, "scan_activation_telemetry", slow_scan)
    caplog.set_level(logging.WARNING, logger="vetmanager.runtime")

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/metrics",
            headers={"Authorization": "Bearer secret-metrics-token"},
        )

    assert response.status_code == 200
    assert "vetmanager_http_requests_total" in response.text
    assert any(
        getattr(record, "event_name", None) == "activation_telemetry_scan_failed"
        and getattr(record, "error_class", None) == "TimeoutError"
        for record in caplog.records
    )
    await engine.dispose()
    storage.reset_storage_state()
