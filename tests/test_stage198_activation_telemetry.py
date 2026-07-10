"""Stage 198 — persisted activation events and new-account funnel metrics."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

import activation_telemetry
import web_routes_account
import storage
from activation_events import (
    classify_activation_device,
    classify_activation_reason,
    record_activation_event_best_effort,
    reset_activation_event_state,
)
from exceptions import AuthError, HostResolutionError, VetmanagerError
from server import mcp
from service_metrics import render_prometheus_metrics, snapshot_service_metrics
from storage import Base, create_database_engine
from storage_models import Account, ActivationEvent, ServiceBearerToken, TokenUsageStat, VetmanagerConnection
from tests.test_web_auth import (
    TEST_ENCRYPTION_KEY,
    _post_with_csrf,
    _prepare_web_db,
    register_account,
)
from web_security import reset_web_security_state


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


def _app_client() -> httpx.AsyncClient:
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=True
    )


async def _login_client(client: httpx.AsyncClient, email: str) -> None:
    await _post_with_csrf(
        client,
        "/login",
        data={"email": email, "password": "Integration-Pass-123"},
    )


async def _events_for(email: str) -> list[ActivationEvent]:
    async with storage.get_session_factory()() as session:
        account = await session.scalar(select(Account).where(Account.email == email))
        assert account is not None
        return list(
            (
                await session.execute(
                    select(ActivationEvent)
                    .where(ActivationEvent.account_id == account.id)
                    .order_by(ActivationEvent.id)
                )
            ).scalars()
        )


def test_stage198_classification_is_closed_and_privacy_safe() -> None:
    assert classify_activation_device(
        {"user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Mobile"}
    ) == "mobile"
    assert classify_activation_device({"user-agent": "Mozilla/5.0 X11 Linux x86_64"}) == "desktop"
    assert classify_activation_device({}) == "unknown"

    assert classify_activation_reason(AuthError("bad key")) == "auth_error"
    assert classify_activation_reason(HostResolutionError("no host")) == "host_resolution_error"
    assert classify_activation_reason(VetmanagerError("boom")) == "vetmanager_error"
    assert classify_activation_reason(ValueError("bad form")) == "validation_error"
    assert classify_activation_reason(RuntimeError("unknown")) == "unknown"


@pytest.mark.asyncio
@respx.mock
async def test_stage198_integration_events_are_persisted_without_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="stage198-integration@example.com",
            password="Integration-Pass-123",
        )

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-198").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-198.vetmanager.cloud"}})
    )
    respx.get("https://clinic-198.vetmanager.cloud/rest/api/client").mock(
        side_effect=[
            httpx.Response(401, json={"error": "unauthorized"}),
            httpx.Response(200, json={"data": []}),
            httpx.Response(200, json={"data": []}),
        ]
    )

    async with _app_client() as client:
        await _login_client(client, "stage198-integration@example.com")
        failed = await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-198", "api_key": "bad-key"},
            page_path="/account",
            headers={"User-Agent": "Mozilla/5.0 (iPhone) Mobile"},
        )
        saved = await _post_with_csrf(
            client,
            "/account/integration",
            data={"domain": "clinic-198", "api_key": "secret-key"},
            page_path="/account",
            headers={"User-Agent": "Mozilla/5.0 X11 Linux x86_64"},
        )

    assert failed.status_code == 400
    assert saved.status_code == 200
    events = await _events_for("stage198-integration@example.com")
    assert [(e.event_name, e.reason_class, e.auth_mode, e.device_class) for e in events] == [
        ("integration_failed", "auth_error", "domain_api_key", "mobile"),
        ("integration_saved", None, "domain_api_key", "desktop"),
    ]
    serialized = "\n".join(str(event.__dict__) for event in events)
    assert "bad-key" not in serialized
    assert "secret-key" not in serialized
    assert "Mozilla" not in serialized

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_stage198_csrf_rejection_does_not_persist_product_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="stage198-csrf@example.com",
            password="Integration-Pass-123",
        )

    async with _app_client() as client:
        await _login_client(client, "stage198-csrf@example.com")
        response = await client.post(
            "/account/integration",
            data={"domain": "clinic-198", "api_key": "bad-key"},
        )

    assert response.status_code == 403
    assert await _events_for("stage198-csrf@example.com") == []

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_stage198_token_copied_event_is_persisted_and_best_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    async with storage.get_session_factory()() as session:
        await register_account(
            session,
            email="stage198-copy@example.com",
            password="Integration-Pass-123",
        )

    async with _app_client() as client:
        await _login_client(client, "stage198-copy@example.com")
        copied = await _post_with_csrf(
            client,
            "/account/telemetry/token-copied",
            data={"kind": "config"},
            page_path="/account",
            headers={"User-Agent": "Mozilla/5.0 X11 Linux x86_64"},
        )

    assert copied.status_code == 204
    events = await _events_for("stage198-copy@example.com")
    assert [(e.event_name, e.copy_kind, e.device_class) for e in events] == [
        ("token_copied", "config", "desktop")
    ]
    assert snapshot_service_metrics()["business_events_total"]["token_copied"] >= 1

    def broken_session_factory():
        raise RuntimeError("telemetry unavailable")

    monkeypatch.setattr(web_routes_account, "get_session_factory", broken_session_factory)
    async with _app_client() as client:
        await _login_client(client, "stage198-copy@example.com")
        copied_without_telemetry = await _post_with_csrf(
            client,
            "/account/telemetry/token-copied",
            data={"kind": "config"},
            page_path="/account",
            headers={"User-Agent": "Mozilla/5.0 X11 Linux x86_64"},
        )
    assert copied_without_telemetry.status_code == 204
    assert snapshot_service_metrics()["business_events_total"]["token_copied"] >= 2

    async with storage.get_session_factory()() as session:
        account = await session.scalar(select(Account).where(Account.email == "stage198-copy@example.com"))
        assert account is not None
        await record_activation_event_best_effort(
            session,
            account_id=account.id,
            event_name="not_allowed",
            device_class="desktop",
        )

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_stage198_metrics_include_new_account_funnel_and_event_breakdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "stage198-metrics.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    storage.reset_storage_state()
    activation_telemetry.reset_activation_telemetry_state()
    reset_activation_event_state()
    reset_web_security_state()
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with storage.get_session_factory()() as session:
        registered = Account(email="registered@example.com", status="active", created_at=NOW, updated_at=NOW)
        failed_then_saved = Account(email="saved@example.com", status="active", created_at=NOW, updated_at=NOW)
        copied = Account(email="copied@example.com", status="active", created_at=NOW, updated_at=NOW)
        used = Account(email="used@example.com", status="active", created_at=NOW, updated_at=NOW)
        old = Account(
            email="old@example.com",
            status="active",
            created_at=NOW - timedelta(days=60),
            updated_at=NOW - timedelta(days=60),
        )
        session.add_all([registered, failed_then_saved, copied, used, old])
        await session.flush()
        for account in (failed_then_saved, copied, used, old):
            session.add(
                VetmanagerConnection(
                    account_id=account.id,
                    auth_mode="domain_api_key",
                    status="active",
                    domain="clinic",
                    created_at=NOW,
                    updated_at=NOW,
                )
            )
            session.add_all([
                ActivationEvent(
                    account_id=account.id,
                    event_name="integration_saved",
                    auth_mode="domain_api_key",
                    device_class="desktop",
                    created_at=NOW,
                )
            ])
        session.add(
            ActivationEvent(
                account_id=failed_then_saved.id,
                event_name="integration_failed",
                auth_mode="domain_api_key",
                device_class="mobile",
                reason_class="auth_error",
                created_at=NOW,
            )
        )
        session.add(
            ActivationEvent(
                account_id=copied.id,
                event_name="token_copied",
                auth_mode="unknown",
                device_class="desktop",
                copy_kind="config",
                created_at=NOW,
            )
        )
        copied_token = ServiceBearerToken(
            account_id=copied.id,
            name="copied",
            status="active",
            allowed_ip_mask="*.*.*.*",
            created_at=NOW,
        )
        copied_token.set_raw_token("vm_st_198copied")
        used_token = ServiceBearerToken(
            account_id=used.id,
            name="used",
            status="active",
            allowed_ip_mask="*.*.*.*",
            created_at=NOW,
            last_used_at=NOW,
        )
        used_token.set_raw_token("vm_st_198used")
        session.add_all([copied_token, used_token])
        await session.flush()
        session.add(TokenUsageStat(bearer_token_id=used_token.id, request_count=1, last_used_at=NOW))
        await session.commit()

        await activation_telemetry.scan_activation_telemetry(session, now=NOW)

    snapshot = snapshot_service_metrics()
    funnel = snapshot["activation_funnel_accounts"]
    assert funnel["registered"] == 5
    assert funnel["new_registered"] == 4
    assert funnel["integration_saved"] == 3
    assert funnel["token_issued"] == 2
    assert funnel["token_copied"] == 1
    assert funnel["first_mcp_request"] == 1
    assert funnel["connected"] == 4
    events = snapshot["activation_event_accounts"]
    assert events["integration_failed|mobile|domain_api_key|auth_error"] == 1
    assert events["integration_saved|desktop|domain_api_key|none"] == 3
    assert events["token_copied|desktop|unknown|none"] == 1

    metrics = render_prometheus_metrics()
    assert 'vetmanager_activation_funnel_accounts{stage="first_mcp_request"} 1' in metrics
    assert (
        'vetmanager_activation_event_accounts'
        '{event="integration_failed",device="mobile",auth_mode="domain_api_key",reason="auth_error"} 1'
    ) in metrics
    assert "old@example.com" not in metrics
    assert "account_id=" not in metrics.split("vetmanager_activation_event_accounts", 1)[1]

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_stage198_activation_events_cascade_cleanup_and_scan_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "stage198-cache.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path}")
    storage.reset_storage_state()
    activation_telemetry.reset_activation_telemetry_state()
    reset_activation_event_state()
    reset_web_security_state()
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with storage.get_session_factory()() as session:
        account = Account(email="cache-one@example.com", status="active", created_at=NOW, updated_at=NOW)
        deleted = Account(email="cache-deleted@example.com", status="active", created_at=NOW, updated_at=NOW)
        account.activation_events.extend(
            [
                ActivationEvent(
                    event_name="token_copied",
                    auth_mode="unknown",
                    device_class="desktop",
                    created_at=NOW,
                ),
                ActivationEvent(
                    event_name="integration_failed",
                    auth_mode="domain_api_key",
                    device_class="mobile",
                    reason_class="auth_error",
                    created_at=NOW - timedelta(days=100),
                ),
            ]
        )
        deleted.activation_events.append(
            ActivationEvent(
                event_name="token_copied",
                auth_mode="unknown",
                device_class="desktop",
                created_at=NOW,
            )
        )
        session.add_all([account, deleted])
        await session.flush()
        await session.delete(deleted)
        await session.commit()

        await activation_telemetry.scan_activation_telemetry(session, now=NOW)
        assert snapshot_service_metrics()["activation_funnel_accounts"]["new_registered"] == 1
        assert snapshot_service_metrics()["activation_event_accounts"] == {
            "token_copied|desktop|unknown|none": 1
        }
        assert await session.scalar(select(func.count()).select_from(ActivationEvent)) == 1

        session.add(
            Account(
                email="cache-two@example.com",
                status="active",
                created_at=NOW + timedelta(seconds=10),
                updated_at=NOW + timedelta(seconds=10),
            )
        )
        await session.commit()

        await activation_telemetry.scan_activation_telemetry(
            session, now=NOW + timedelta(seconds=30)
        )
        assert snapshot_service_metrics()["activation_funnel_accounts"]["new_registered"] == 1

        await activation_telemetry.scan_activation_telemetry(
            session, now=NOW + timedelta(seconds=61)
        )
        assert snapshot_service_metrics()["activation_funnel_accounts"]["new_registered"] == 2

    await engine.dispose()
    storage.reset_storage_state()
