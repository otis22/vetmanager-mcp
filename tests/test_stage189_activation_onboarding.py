"""Stage 189 activation and onboarding follow-up."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from playwright.sync_api import Page

from scripts.product_metrics_report import collect_metrics, format_json, format_markdown
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TokenUsageStat,
    VetmanagerConnection,
)
from web_html import render_account_page


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2026, 7, 9, 12, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def activation_session(tmp_path, sqlite_session_factory_builder, now_utc):
    factory = await sqlite_session_factory_builder(tmp_path / "stage189.db")

    async with factory() as session:
        connected_recent = Account(
            email="connected-recent@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=40),
            updated_at=now_utc - timedelta(days=40),
        )
        connected_recent_two = Account(
            email="connected-recent-two@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=20),
            updated_at=now_utc - timedelta(days=20),
        )
        connected_stale = Account(
            email="connected-stale@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=40),
            updated_at=now_utc - timedelta(days=40),
        )
        connected_expired = Account(
            email="connected-expired@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=40),
            updated_at=now_utc - timedelta(days=40),
        )
        no_connection_no_token = Account(
            email="no-connection@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=2),
            updated_at=now_utc - timedelta(days=2),
        )
        no_connection_with_token = Account(
            email="token-only@example.com",
            password_hash="h",
            status=ACCOUNT_STATUS_ACTIVE,
            created_at=now_utc - timedelta(days=40),
            updated_at=now_utc - timedelta(days=40),
        )
        session.add_all([
            connected_recent,
            connected_recent_two,
            connected_stale,
            connected_expired,
            no_connection_no_token,
            no_connection_with_token,
        ])
        await session.flush()

        for account in (connected_recent, connected_recent_two, connected_stale, connected_expired):
            session.add(VetmanagerConnection(
                account_id=account.id,
                auth_mode="domain_api_key",
                status="active",
            ))

        tokens = []
        for idx, account in enumerate(
            (connected_recent, connected_recent_two, connected_stale, no_connection_with_token),
            start=1,
        ):
            token = ServiceBearerToken(
                account_id=account.id,
                name=f"token-{idx}",
                token_prefix=f"vm_st_{idx}",
                token_hash=f"hash-{idx}",
                status=TOKEN_STATUS_ACTIVE,
                created_at=now_utc - timedelta(days=10),
            )
            session.add(token)
            tokens.append(token)
        session.add(ServiceBearerToken(
            account_id=connected_expired.id,
            name="token-expired",
            token_prefix="vm_st_expired",
            token_hash="hash-expired",
            status=TOKEN_STATUS_ACTIVE,
            expires_at=now_utc - timedelta(days=1),
            created_at=now_utc - timedelta(days=10),
        ))
        await session.flush()

        session.add(TokenUsageStat(
            bearer_token_id=tokens[0].id,
            request_count=10,
            last_used_at=now_utc - timedelta(days=1),
        ))
        session.add(TokenUsageStat(
            bearer_token_id=tokens[1].id,
            request_count=5,
            last_used_at=now_utc - timedelta(days=3),
        ))
        session.add(TokenUsageStat(
            bearer_token_id=tokens[2].id,
            request_count=1,
            last_used_at=now_utc - timedelta(days=20),
        ))
        await session.commit()

    return factory


def _account_page(
    *,
    active_connection: object | None = None,
    integration_health_status: str = "active",
    bearer_tokens: list[dict[str, object]] | None = None,
    oauth_grants: list[dict[str, object]] | None = None,
    activation_now: datetime | None = None,
) -> str:
    account = Account(id=1, email="owner@example.org", status="active")
    tokens = bearer_tokens or []
    return render_account_page(
        account,
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1 if active_connection is not None else 0,
        bearer_token_count=len(tokens),
        active_connection=active_connection,
        integration_health_status=integration_health_status,
        integration_health_reason="ok",
        bearer_tokens=tokens,
        oauth_grants=oauth_grants or [],
        activation_now=activation_now,
    )


class _Connection:
    auth_mode = "domain_api_key"
    domain = "clinic"
    status = "active"


def test_activation_panel_guides_new_account_to_connection() -> None:
    html = _account_page()

    assert 'data-testid="activation-status"' in html
    assert 'data-activation-state="needs_connection"' in html
    assert "Подключите Vetmanager" in html
    assert "secret-api-key" not in html
    assert "vm_st_" not in html


def test_activation_panel_guides_connected_account_to_token() -> None:
    html = _account_page(active_connection=_Connection())

    assert 'data-activation-state="needs_token"' in html
    assert "Выпустите Bearer token" in html


def test_activation_panel_guides_ready_unused_account_to_client_use(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "ops",
                "token_prefix": "vm_st_safe_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc + timedelta(days=21),
                "expires_at": "2026-07-30 12:00 UTC",
                "last_used_at_raw": None,
                "last_used_at": "Never",
                "request_count": 0,
            }
        ],
    )

    assert 'data-activation-state="needs_client_use"' in html
    assert "Подключите MCP-клиент" in html


def test_activation_panel_treats_request_count_as_client_usage(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "ops",
                "token_prefix": "vm_st_safe_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc + timedelta(days=21),
                "expires_at": "2026-07-30 12:00 UTC",
                "last_used_at_raw": None,
                "last_used_at": "Never",
                "request_count": 3,
            }
        ],
    )

    assert 'data-activation-state="ready"' in html
    assert "Готово к работе" in html


def test_activation_panel_logs_invalid_request_count_shape(now_utc, caplog) -> None:
    with caplog.at_level("WARNING"):
        html = _account_page(
            active_connection=_Connection(),
            activation_now=now_utc,
            bearer_tokens=[
                {
                    "id": 10,
                    "name": "ops",
                    "token_prefix": "vm_st_safe_prefix",
                    "access_label": "Read only",
                    "privacy_label": "Depersonalized",
                    "status": "active",
                    "ip_mask": "10.20.30.*",
                    "expires_at_raw": now_utc + timedelta(days=21),
                    "expires_at": "2026-07-30 12:00 UTC",
                    "last_used_at_raw": None,
                    "last_used_at": "Never",
                    "request_count": object(),
                }
            ],
        )

    assert 'data-activation-state="needs_client_use"' in html
    assert "Подключите MCP-клиент" in html
    assert any(
        record.levelname == "WARNING"
        and getattr(record, "event_name", None) == "activation_request_count_parse_failed"
        and getattr(record, "token_id", None) == 10
        for record in caplog.records
    )


def test_activation_panel_ignores_historical_usage_on_unusable_token(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "old",
                "token_prefix": "vm_st_old_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "revoked",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": None,
                "expires_at": "No expiry",
                "last_used_at_raw": now_utc - timedelta(days=1),
                "last_used_at": "2026-07-08 12:00 UTC",
                "request_count": 5,
            },
            {
                "id": 11,
                "name": "fresh",
                "token_prefix": "vm_st_fresh_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc + timedelta(days=21),
                "expires_at": "2026-07-30 12:00 UTC",
                "last_used_at_raw": None,
                "last_used_at": "Never",
                "request_count": 0,
            },
        ],
    )

    assert 'data-activation-state="needs_client_use"' in html
    assert "Подключите MCP-клиент" in html


def test_activation_panel_ready_state(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "ops",
                "token_prefix": "vm_st_safe_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc + timedelta(days=21),
                "expires_at": "2026-07-30 12:00 UTC",
                "last_used_at_raw": now_utc,
                "last_used_at": "2026-07-09 12:00 UTC",
                "request_count": 0,
            }
        ],
    )

    assert 'data-activation-state="ready"' in html
    assert "Готово к работе" in html
    assert "Vetmanager integration active" not in html
    assert "Bearer token issued and active" not in html
    assert "MCP client made at least one request" not in html
    assert "ChatGPT OAuth connection configured" not in html
    assert "Интеграция Vetmanager активна" in html
    assert "Bearer token выпущен и активен" in html
    assert "MCP-клиент сделал хотя бы один запрос" in html
    assert "Подключение ChatGPT OAuth настроено" in html


def test_activation_panel_treats_expired_token_as_missing_token(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "ops",
                "token_prefix": "vm_st_safe_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc - timedelta(minutes=1),
                "expires_at": "2026-07-09 11:59 UTC",
                "last_used_at_raw": now_utc,
                "last_used_at": "2026-07-09 12:00 UTC",
                "request_count": 4,
            }
        ],
    )

    assert 'data-activation-state="needs_token"' in html
    assert "Выпустите Bearer token" in html


def test_activation_panel_treats_any_last_used_at_as_client_usage(now_utc) -> None:
    html = _account_page(
        active_connection=_Connection(),
        activation_now=now_utc,
        bearer_tokens=[
            {
                "id": 10,
                "name": "ops",
                "token_prefix": "vm_st_safe_prefix",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "active",
                "ip_mask": "10.20.30.*",
                "expires_at_raw": now_utc + timedelta(days=21),
                "expires_at": "2026-07-30 12:00 UTC",
                "last_used_at_raw": now_utc - timedelta(days=8),
                "last_used_at": "2026-07-01 12:00 UTC",
                "request_count": 4,
            }
        ],
    )

    assert 'data-activation-state="ready"' in html
    assert "Готово к работе" in html


def test_activation_panel_does_not_overflow_common_viewports(page: Page) -> None:
    html = _account_page(active_connection=_Connection())

    for viewport in (
        {"width": 1024, "height": 900},
        {"width": 760, "height": 900},
        {"width": 390, "height": 900},
    ):
        page.set_viewport_size(viewport)
        page.set_content(html)
        page.wait_for_selector('[data-testid="activation-status"]')
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > window.innerWidth"
        )
        assert overflow is False
        checklist_rows = page.evaluate(
            """() => {
                const container = document.querySelector('[data-testid="activation-status"]');
                const list = container.querySelector('ol');
                const containerBox = container.getBoundingClientRect();
                const nodes = Array.from(container.querySelectorAll('li'));
                return {
                    count: nodes.length,
                    listOverflows: list.scrollWidth > list.clientWidth,
                    rowsOutOfBounds: nodes.some((node) => {
                        const box = node.getBoundingClientRect();
                        return box.left < containerBox.left - 1 || box.right > containerBox.right + 1;
                    }),
                };
            }"""
        )
        assert checklist_rows["count"] == 4
        assert checklist_rows["listOverflows"] is False
        assert checklist_rows["rowsOutOfBounds"] is False


@pytest.mark.asyncio
async def test_product_metrics_activation_funnel(activation_session, now_utc) -> None:
    metrics = await collect_metrics(activation_session, now=now_utc, top_n=5)

    assert metrics["activation_funnel"] == {
        "connected": 4,
        "with_tokens": 5,
        "with_active_tokens": 4,
        "with_recent_usage": 2,
        "ready_for_mcp": 3,
        "needs_connection": 2,
        "needs_token": 1,
        "needs_client_use": 1,
    }


@pytest.mark.asyncio
async def test_product_metrics_activation_output_and_masking(activation_session, now_utc) -> None:
    metrics = await collect_metrics(activation_session, now=now_utc, top_n=5)
    markdown = format_markdown(metrics, now=now_utc)
    parsed = json.loads(format_json(metrics, now=now_utc))

    assert "## Activation funnel" in markdown
    assert "- ready for MCP: **3**" in markdown
    assert parsed["activation_funnel"]["needs_client_use"] == 1
    assert "connected-recent@example.com" not in markdown
    assert "connected-recent-two@example.com" not in markdown
    assert "token-only@example.com" not in markdown
