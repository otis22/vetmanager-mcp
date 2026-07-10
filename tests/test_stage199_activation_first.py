"""Stage 199 — activation-first account page.

Covers the step-N-of-3 stepper, details-based section collapse rules per
activation state, anchor-open JS, and viewport overflow regression for the
restructured page.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import Page

from storage_models import Account
from web_html import render_account_page


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
        active_connection_count=0,
        bearer_token_count=0,
        active_connection=None,
        integration_health_status="unknown",
        integration_health_reason="ok",
        bearer_tokens=[],
        oauth_grants=[],
        activation_now=NOW,
    )
    kwargs.update(overrides)
    return render_account_page(account, **kwargs)


def _needs_connection() -> str:
    return _account_page()


def _needs_token() -> str:
    return _account_page(active_connection=_Connection(), integration_health_status="active")


def _needs_client_use() -> str:
    return _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        bearer_tokens=[_token_view()],
    )


def _ready() -> str:
    return _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        bearer_tokens=[_token_view(request_count=7)],
    )


def _section_is_open(html: str, testid: str) -> bool:
    match = re.search(rf'data-testid="{testid}"([^>]*)>', html)
    assert match is not None, f"section {testid} not found"
    return "open" in match.group(1)


# ── Stepper ──────────────────────────────────────────────────────────────────


def test_stepper_reflects_activation_progress() -> None:
    assert "Шаг 1 из 3 — Подключите Vetmanager" in _needs_connection()
    assert "Шаг 2 из 3 — Выпустите Bearer token" in _needs_token()
    assert "Шаг 3 из 3 — Подключите MCP-клиент" in _needs_client_use()


def test_stepper_disappears_when_ready() -> None:
    assert 'data-testid="activation-stepper"' not in _ready()


# ── Section collapse rules ───────────────────────────────────────────────────


def test_needs_connection_shows_integration_and_hides_noise() -> None:
    html = _needs_connection()
    assert _section_is_open(html, "integration-section")
    assert not _section_is_open(html, "account-meta")
    assert not _section_is_open(html, "token-section")
    assert not _section_is_open(html, "tokens-list-section")
    assert not _section_is_open(html, "chatgpt-section")


def test_needs_token_opens_token_section_and_closes_integration() -> None:
    html = _needs_token()
    assert _section_is_open(html, "token-section")
    assert not _section_is_open(html, "integration-section")
    assert not _section_is_open(html, "account-meta")


def test_needs_client_use_keeps_forms_collapsed_but_lists_tokens() -> None:
    html = _needs_client_use()
    assert not _section_is_open(html, "integration-section")
    assert not _section_is_open(html, "token-section")
    assert _section_is_open(html, "tokens-list-section")


def test_ready_opens_meta_and_chatgpt() -> None:
    html = _ready()
    assert _section_is_open(html, "account-meta")
    assert _section_is_open(html, "chatgpt-section")
    assert _section_is_open(html, "tokens-list-section")
    assert not _section_is_open(html, "integration-section")


def test_error_or_message_forces_owning_section_open() -> None:
    integration_error = _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        integration_error="boom",
    )
    assert _section_is_open(integration_error, "integration-section")

    token_error = _needs_client_use().replace("", "")
    html = _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        bearer_tokens=[_token_view()],
        token_error="bad input",
    )
    assert _section_is_open(html, "token-section")

    reauth = _account_page(
        active_connection=_Connection(),
        integration_health_status="reauth_required",
    )
    assert _section_is_open(reauth, "integration-section")


def test_all_sections_remain_in_dom_when_collapsed() -> None:
    """Collapse must hide, not remove — forms and tables stay addressable."""
    html = _needs_connection()
    for testid in (
        "integration-form",
        "token-form",
        "chatgpt-connect-instructions",
        "logout-form",
    ):
        assert f'data-testid="{testid}"' in html


def test_anchor_open_js_present() -> None:
    html = _needs_connection()
    assert "openForHash" in html
    assert "a[href^=\"#\"]" in html


# ── Viewport regression for the restructured page ────────────────────────────


def _just_issued() -> str:
    return _account_page(
        active_connection=_Connection(),
        integration_health_status="active",
        bearer_tokens=[_token_view()],
        issued_raw_token="vm_st_f1QHoiqKnkTyJltLCMyfyQhXBhxmtckdJ-KqBkmV9NM",
        token_success="Bearer token выпущен.",
    )


def test_activation_first_page_does_not_overflow_common_viewports(page: Page) -> None:
    for html in (_needs_connection(), _needs_token(), _needs_client_use(), _ready(), _just_issued()):
        for viewport in (
            {"width": 1024, "height": 900},
            {"width": 760, "height": 900},
            {"width": 390, "height": 900},
        ):
            page.set_viewport_size(viewport)
            page.set_content(html)
            page.wait_for_selector("h1")
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth > window.innerWidth"
            )
            assert overflow is False

        # Opening every section must not overflow either.
        page.set_viewport_size({"width": 390, "height": 900})
        page.set_content(html)
        page.evaluate(
            "() => document.querySelectorAll('details').forEach((d) => { d.open = true; })"
        )
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > window.innerWidth"
        )
        assert overflow is False
