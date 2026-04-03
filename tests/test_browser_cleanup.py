"""Regression coverage for browser account cleanup helper."""

from unittest.mock import patch

import pytest

import request_credentials
from server import mcp


@pytest.mark.browser
def test_browser_cleanup_removes_account_and_related_entities(
    page,
    live_server_url: str,
    mock_domain_api_key_upstream,
    browser_account_cleanup,
    run_async,
) -> None:
    mocked = mock_domain_api_key_upstream(
        domain="browser-cleanup-domain",
        api_key="browser-cleanup-api-key",
    )
    account_email = "browser-cleanup@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill(account_email)
    page.locator('input[name="password"]').fill("Browser-Cleanup-Pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    integration_form = page.locator('form[data-auth-wizard="true"]')
    domain_api_key_panel = integration_form.locator('[data-mode-panel="domain_api_key"]')
    domain_api_key_panel.locator('input[name="domain"]').fill(mocked.domain)
    domain_api_key_panel.locator('input[name="api_key"]').fill(mocked.api_key)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    page.locator('form[action="/account/tokens"] input[name="token_name"]').fill("Browser cleanup token")
    page.locator('form[action="/account/tokens"] input[name="expires_in_days"]').fill("7")
    page.locator('form[action="/account/tokens"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    raw_token = page.locator("#issued-token-value").text_content()
    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None

    report = browser_account_cleanup.cleanup_now()

    assert report.deleted_accounts == 1
    assert report.before["accounts"] == 1
    assert report.before["vetmanager_connections"] == 1
    assert report.before["service_bearer_tokens"] == 1
    assert report.before["token_usage_stats"] == 1
    assert report.before["token_usage_logs"] >= 2
    assert report.after == {
        "accounts": 0,
        "vetmanager_connections": 0,
        "service_bearer_tokens": 0,
        "token_usage_stats": 0,
        "token_usage_logs": 0,
    }
