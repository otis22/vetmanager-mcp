"""Stage 197 — one-click token issuance and first-MCP-request onboarding.

Covers the quick-issue panel with explicit IP-scope choice, manual form
collapse, ready-made config copy + token_copied telemetry, per-client connect
instructions at needs_client_use, and the activation-status polling endpoint.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

import storage
from server import mcp
from service_metrics import snapshot_service_metrics
from storage_models import Account, ServiceBearerToken
from web_html import QUICK_TOKEN_NAME, render_account_page

from tests.test_web_auth import (
    _mock_active_connection_health,
    _post_with_csrf,
    _prepare_web_db,
    _register_account_with_active_connection,
)


NOW = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)


class _Connection:
    auth_mode = "domain_api_key"
    domain = "clinic"
    status = "active"


def _token_view(**overrides) -> dict[str, object]:
    token = {
        "id": 10,
        "name": "ops",
        "token_prefix": "vm_st_safe",
        "access_label": "Analytics",
        "privacy_label": "Depersonalized",
        "status": "active",
        "ip_mask": "*.*.*.*",
        "expires_at_raw": NOW + timedelta(days=21),
        "expires_at": "2026-07-31 12:00 UTC",
        "last_used_at_raw": None,
        "last_used_at": "Never",
        "request_count": 0,
    }
    token.update(overrides)
    return token


def _account_page(**overrides) -> str:
    account = Account(id=1, email="owner@example.org", status="active")
    kwargs = dict(
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1,
        bearer_token_count=0,
        active_connection=_Connection(),
        integration_health_status="active",
        integration_health_reason="ok",
        bearer_tokens=[],
        oauth_grants=[],
        activation_now=NOW,
    )
    kwargs.update(overrides)
    return render_account_page(account, **kwargs)


async def _login_client(client: httpx.AsyncClient, email: str) -> None:
    await _post_with_csrf(
        client,
        "/login",
        data={"email": email, "password": "Integration-Pass-123"},
    )


def _app_client() -> httpx.AsyncClient:
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(
        transport=transport, base_url="http://testserver", follow_redirects=True
    )


# ── 197.2: quick-issue panel render rules ────────────────────────────────────


def test_quick_issue_panel_shown_only_at_needs_token() -> None:
    needs_token = _account_page()
    assert 'data-testid="token-quick-issue"' in needs_token
    assert f'value="{QUICK_TOKEN_NAME}"' in needs_token
    assert 'name="expires_in_days" value="30"' in needs_token
    assert 'name="access_preset" value="report_ai"' in needs_token
    assert 'data-testid="token-quick-ip-any"' in needs_token
    assert 'data-testid="token-quick-ip-current"' in needs_token
    # "any" is the guided default with an honest warning next to it.
    assert 'value="any" checked' in needs_token

    needs_connection = _account_page(active_connection=None, integration_health_status="unknown")
    assert 'data-testid="token-quick-issue"' not in needs_connection

    needs_client_use = _account_page(bearer_tokens=[_token_view()])
    assert 'data-testid="token-quick-issue"' not in needs_client_use


def test_manual_form_collapsed_behind_quick_panel_but_open_otherwise() -> None:
    needs_token = _account_page()
    assert 'data-testid="token-manual-form" >' in needs_token or (
        'data-testid="token-manual-form"' in needs_token
        and 'data-testid="token-manual-form" open' not in needs_token
    )

    ready = _account_page(bearer_tokens=[_token_view(request_count=5)])
    assert 'data-testid="token-manual-form" open' in ready

    with_error = _account_page(token_error="boom")
    assert 'data-testid="token-manual-form" open' in with_error


# ── 197.2: quick-issue route behaviour ───────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_quick_issue_any_ip_stores_wildcard_and_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA=")
    await _register_account_with_active_connection(email="quick-any@example.com")
    _mock_active_connection_health("clinic")

    async with _app_client() as client:
        await _login_client(client, "quick-any@example.com")
        response = await _post_with_csrf(
            client,
            "/account/tokens",
            data={
                "token_name": QUICK_TOKEN_NAME,
                "expires_in_days": "30",
                "access_preset": "report_ai",
                "quick_ip_choice": "any",
            },
            page_path="/account",
        )

    assert response.status_code == 200
    assert "vm_st_" in response.text

    async with storage.get_session_factory()() as session:
        token = (
            await session.execute(select(ServiceBearerToken))
        ).scalars().one()
    assert token.allowed_ip_mask == "*.*.*.*"
    assert token.name == QUICK_TOKEN_NAME

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_quick_issue_current_ip_binds_to_request_ip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA=")
    await _register_account_with_active_connection(email="quick-current@example.com")
    _mock_active_connection_health("clinic")

    async with _app_client() as client:
        await _login_client(client, "quick-current@example.com")
        response = await _post_with_csrf(
            client,
            "/account/tokens",
            data={
                "token_name": "",
                "expires_in_days": "30",
                "access_preset": "report_ai",
                "quick_ip_choice": "current",
            },
            page_path="/account",
        )

    assert response.status_code == 200

    async with storage.get_session_factory()() as session:
        token = (
            await session.execute(select(ServiceBearerToken))
        ).scalars().one()
    # httpx ASGI transport reports a concrete client IP; the token is bound to it.
    assert token.allowed_ip_mask not in ("", "*.*.*.*")
    # Blank name in the quick flow falls back to the default quick name.
    assert token.name == QUICK_TOKEN_NAME

    await engine.dispose()
    storage.reset_storage_state()


# ── 197.3: issued panel config copy + instructions ───────────────────────────


def test_issued_token_panel_has_open_instructions_and_config_copy() -> None:
    html = _account_page(
        bearer_tokens=[_token_view()],
        issued_raw_token="vm_st_fresh_secret",
        token_success="Bearer token выпущен.",
    )
    assert 'data-testid="issued-token-instructions"' in html
    assert '<details class="token-flash-example" open' in html
    assert 'id="issued-token-config"' in html
    assert 'data-copy-kind="config"' in html
    assert "Скопировать готовый конфиг" in html


def test_client_instructions_become_primary_content_at_needs_client_use() -> None:
    html = _account_page(bearer_tokens=[_token_view()])
    assert 'data-testid="client-connect-instructions"' in html
    assert "Cursor / Claude Code" in html
    assert "ChatGPT" in html
    assert "ВАШ_ТОКЕН" in html
    # Waiting indicator with polling marker.
    assert 'data-testid="activation-waiting"' in html
    assert 'data-poll-activation="needs_client_use"' in html

    ready = _account_page(bearer_tokens=[_token_view(request_count=5)])
    assert 'data-testid="client-connect-instructions"' not in ready
    assert 'data-testid="activation-waiting"' not in ready


def test_copy_buttons_report_token_copied_telemetry() -> None:
    html = _account_page(issued_raw_token="vm_st_fresh_secret")
    assert "/account/telemetry/token-copied" in html
    assert 'data-copy-kind="token"' in html
    assert 'data-copy-kind="mcp_url"' in html


# ── 197.3: telemetry endpoint ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_copied_endpoint_records_business_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    from web_auth import register_account

    async with storage.get_session_factory()() as session:
        await register_account(
            session, email="copied@example.com", password="Integration-Pass-123"
        )

    before = snapshot_service_metrics()["business_events_total"].get("token_copied", 0)
    async with _app_client() as client:
        await _login_client(client, "copied@example.com")
        response = await _post_with_csrf(
            client,
            "/account/telemetry/token-copied",
            data={"kind": "config"},
            page_path="/account",
        )

    assert response.status_code == 204
    after = snapshot_service_metrics()["business_events_total"].get("token_copied", 0)
    assert after == before + 1

    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_token_copied_endpoint_requires_session_and_csrf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    from web_auth import register_account

    async with storage.get_session_factory()() as session:
        await register_account(
            session, email="copied-sec@example.com", password="Integration-Pass-123"
        )

    async with _app_client() as client:
        unauth = await client.post(
            "/account/telemetry/token-copied", data={"kind": "token"}
        )
        assert unauth.status_code == 401

        await _login_client(client, "copied-sec@example.com")
        bad_csrf = await client.post(
            "/account/telemetry/token-copied",
            data={"kind": "token", "csrf_token": "forged"},
        )
        assert bad_csrf.status_code == 403

    await engine.dispose()
    storage.reset_storage_state()


# ── 197.4: activation-status polling endpoint ────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_activation_status_endpoint_reports_current_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA=")
    from web_auth import register_account

    async with storage.get_session_factory()() as session:
        await register_account(
            session, email="poll@example.com", password="Integration-Pass-123"
        )

    async with _app_client() as client:
        unauth = await client.get("/account/activation-status")
        assert unauth.status_code == 401

        await _login_client(client, "poll@example.com")
        fresh = await client.get("/account/activation-status")
        assert fresh.status_code == 200
        assert fresh.json() == {"state": "needs_connection"}

    await _register_account_with_active_connection(email="poll2@example.com")
    _mock_active_connection_health("clinic")
    async with _app_client() as client:
        await _login_client(client, "poll2@example.com")
        connected = await client.get("/account/activation-status")
        assert connected.json() == {"state": "needs_token"}

    await engine.dispose()
    storage.reset_storage_state()
