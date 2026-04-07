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
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Browser-Cleanup-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    page.get_by_test_id("integration-domain").fill(mocked.domain)
    page.get_by_test_id("integration-api-key").fill(mocked.api_key)
    page.get_by_test_id("integration-submit").click()
    page.wait_for_load_state("networkidle")

    page.get_by_test_id("token-name").fill("Browser cleanup token")
    page.get_by_test_id("token-expires-in-days").fill("7")
    page.get_by_test_id("token-submit").click()
    page.wait_for_load_state("networkidle")

    raw_token = page.get_by_test_id("issued-token-value").text_content()
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
