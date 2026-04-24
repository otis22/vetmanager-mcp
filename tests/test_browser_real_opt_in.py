"""Opt-in real browser tests against a dedicated Vetmanager contour."""

import os
from unittest.mock import patch

import pytest

import auth.request as auth_request
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
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Real-Browser-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    page.get_by_test_id("integration-domain").fill(TEST_DOMAIN)
    page.get_by_test_id("integration-api-key").fill(TEST_API_KEY)
    page.get_by_test_id("integration-submit").click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()

    page.get_by_test_id("token-name").fill("Real browser API token")
    page.get_by_test_id("token-expires-in-days").fill("7")
    page.get_by_test_id("token-ip-mask").fill("*.*.*.*")
    page.get_by_test_id("token-confirm-wildcard-ip").check()
    page.get_by_test_id("token-submit").click()
    page.wait_for_load_state("networkidle")

    raw_token = page.get_by_test_id("issued-token-value").text_content()
    with patch.object(
        auth_request,
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
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Real-Browser-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    page.get_by_test_id("auth-mode-user-token-radio").check()
    page.get_by_test_id("panel-user-token").wait_for(state="visible")

    real_domain = TEST_DOMAIN or TEST_USER_TOKEN_BASE_URL.split("//", 1)[-1].split(".", 1)[0]
    page.get_by_test_id("integration-domain-user-token").fill(real_domain)
    page.get_by_test_id("integration-vm-login").fill(TEST_USER_LOGIN)
    page.get_by_test_id("integration-vm-password").fill(TEST_USER_PASSWORD)
    page.get_by_test_id("integration-submit").click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()

    page.get_by_test_id("token-name").fill("Real browser user token")
    page.get_by_test_id("token-expires-in-days").fill("7")
    page.get_by_test_id("token-ip-mask").fill("*.*.*.*")
    page.get_by_test_id("token-confirm-wildcard-ip").check()
    page.get_by_test_id("token-submit").click()
    page.wait_for_load_state("networkidle")

    raw_token = page.get_by_test_id("issued-token-value").text_content()
    with patch.object(
        auth_request,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_users", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
