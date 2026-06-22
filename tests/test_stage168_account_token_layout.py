"""Stage 168 account token table layout tests."""

from __future__ import annotations

from playwright.sync_api import Page

from storage_models import Account
from web_html import render_account_page


def _render_account_with_tokens() -> str:
    account = Account(id=1, email="ops@example.com", status="active")
    return render_account_page(
        account,
        csrf_token="csrf-token",
        script_nonce="nonce",
        active_connection_count=1,
        bearer_token_count=2,
        active_connection=None,
        integration_health_status="active",
        integration_health_reason="ok",
        bearer_tokens=[
            {
                "id": 10,
                "name": "vetmanager-ai-assistant4234-with-a-very-long-human-readable-name",
                "token_prefix": "vm_st_Q9Uwh5",
                "access_label": "Legacy/custom",
                "privacy_label": "Standard",
                "status": "active",
                "ip_mask": "*.*.*.*",
                "expires_at": "2027-06-07 18:29 UTC",
                "last_used_at": "2026-04-24 22:22 UTC",
                "request_count": 2818,
            },
            {
                "id": 11,
                "name": "codex bridge",
                "token_prefix": "vm_st_QE53hD",
                "access_label": "Read only",
                "privacy_label": "Depersonalized",
                "status": "expired",
                "ip_mask": "10.20.30.*",
                "expires_at": "2026-06-20 08:27 UTC",
                "last_used_at": "Never",
                "request_count": 0,
            },
        ],
        oauth_grants=[],
    )


def test_account_token_list_uses_compact_primary_columns() -> None:
    html = _render_account_with_tokens()

    assert 'class="card account-card"' in html
    assert 'class="token-table" data-testid="token-list"' in html
    assert html.count("<th>") == 6
    assert "<th>Token</th><th>Access</th><th>Status</th><th>Last used</th><th>Requests</th><th>Actions</th>" in html
    assert "<th>Name</th>" not in html
    assert "<th>Prefix</th>" not in html
    assert "<th>Privacy</th>" not in html
    assert "<th>IP mask</th>" not in html
    assert "<th>Expires</th>" not in html

    assert '<summary>Details</summary>' in html
    assert "<dt>Privacy</dt>" in html
    assert "<dt>IP mask</dt>" in html
    assert "<dt>Expires</dt>" in html
    assert "Depersonalized" in html
    assert "10.20.30.*" in html
    assert 'class="token-action-cell" data-label="Actions"' in html
    assert 'action="/account/tokens/10/revoke"' in html
    assert "<button type=\"submit\">Revoke</button>" in html


def test_account_token_list_does_not_overflow_common_viewports(page: Page) -> None:
    html = _render_account_with_tokens()

    def assert_no_horizontal_overflow() -> None:
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > window.innerWidth"
        )
        assert overflow is False

        action_cell_right = page.locator(".token-action-cell").first.evaluate(
            "(node) => node.getBoundingClientRect().right"
        )
        viewport_width = page.evaluate("() => window.innerWidth")
        assert action_cell_right <= viewport_width

    for viewport in (
        {"width": 1024, "height": 900},
        {"width": 900, "height": 900},
        {"width": 760, "height": 900},
        {"width": 640, "height": 900},
        {"width": 390, "height": 900},
    ):
        page.set_viewport_size(viewport)
        page.set_content(html)
        page.wait_for_selector('[data-testid="token-list"]')

        assert_no_horizontal_overflow()
        page.locator(".token-details").evaluate_all(
            "(nodes) => nodes.forEach((node) => { node.open = true; })"
        )
        assert_no_horizontal_overflow()

    assert "@media (max-width: 780px)" in html
    assert 'data-label="Actions"' in html
