"""Opt-in real browser tests against a dedicated Vetmanager contour."""

import os
from unittest.mock import patch

import pytest

import request_credentials
from server import mcp


RUN_REAL_BROWSER_TESTS = os.environ.get("RUN_REAL_BROWSER_TESTS", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
TEST_DOMAIN = os.environ.get("TEST_DOMAIN", "")
TEST_API_KEY = os.environ.get("TEST_API_KEY", "")
TEST_USER_TOKEN_BASE_URL = os.environ.get("TEST_USER_TOKEN_BASE_URL", "")
TEST_USER_LOGIN = os.environ.get("TEST_USER_LOGIN", "")
TEST_USER_PASSWORD = os.environ.get("TEST_USER_PASSWORD", "")

skip_if_real_browser_not_enabled = pytest.mark.skipif(
    not RUN_REAL_BROWSER_TESTS,
    reason="Set RUN_REAL_BROWSER_TESTS=1 to enable opt-in real browser tests.",
)
skip_if_no_real_api_key_flow = pytest.mark.skipif(
    not TEST_DOMAIN or not TEST_API_KEY,
    reason="Need TEST_DOMAIN and TEST_API_KEY for real browser API-key flow.",
)
skip_if_no_real_user_token_flow = pytest.mark.skipif(
    not TEST_USER_TOKEN_BASE_URL or not TEST_USER_LOGIN or not TEST_USER_PASSWORD,
    reason="Need TEST_USER_TOKEN_BASE_URL, TEST_USER_LOGIN and TEST_USER_PASSWORD for real browser user-token flow.",
)


@pytest.mark.browser
@pytest.mark.real_browser
@skip_if_real_browser_not_enabled
@skip_if_no_real_api_key_flow
def test_real_browser_domain_api_key_flow_can_issue_bearer_and_call_mcp(
    page,
    live_server_url: str,
    browser_account_cleanup,
    run_async,
) -> None:
    account_email = "real-browser-api@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill(account_email)
    page.locator('input[name="password"]').fill("real-browser-pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    integration_form = page.locator('form[data-auth-wizard="true"]')
    api_panel = integration_form.locator('[data-mode-panel="domain_api_key"]')
    api_panel.locator('input[name="domain"]').fill(TEST_DOMAIN)
    api_panel.locator('input[name="api_key"]').fill(TEST_API_KEY)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()

    page.locator('form[action="/account/tokens"] input[name="token_name"]').fill("Real browser API token")
    page.locator('form[action="/account/tokens"] input[name="expires_in_days"]').fill("7")
    page.locator('form[action="/account/tokens"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    raw_token = page.locator("#issued-token-value").input_value()
    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content


@pytest.mark.browser
@pytest.mark.real_browser
@skip_if_real_browser_not_enabled
@skip_if_no_real_user_token_flow
def test_real_browser_user_token_flow_can_issue_bearer_and_call_mcp(
    page,
    live_server_url: str,
    browser_account_cleanup,
    run_async,
) -> None:
    account_email = "real-browser-user@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill(account_email)
    page.locator('input[name="password"]').fill("real-browser-pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    integration_form = page.locator('form[data-auth-wizard="true"]')
    integration_form.locator('input[name="auth_mode"][value="user_token"]').check()
    page.wait_for_timeout(50)

    user_panel = integration_form.locator('[data-mode-panel="user_token"]')
    real_domain = TEST_DOMAIN or TEST_USER_TOKEN_BASE_URL.split("//", 1)[-1].split(".", 1)[0]
    user_panel.locator('input[name="domain"]').fill(real_domain)
    user_panel.locator('input[name="vm_login"]').fill(TEST_USER_LOGIN)
    user_panel.locator('input[name="vm_password"]').fill(TEST_USER_PASSWORD)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()

    page.locator('form[action="/account/tokens"] input[name="token_name"]').fill("Real browser user token")
    page.locator('form[action="/account/tokens"] input[name="expires_in_days"]').fill("7")
    page.locator('form[action="/account/tokens"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    raw_token = page.locator("#issued-token-value").input_value()
    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_users", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
