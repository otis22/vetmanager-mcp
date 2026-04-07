"""Browser happy-path coverage for login/password -> user token onboarding."""

from unittest.mock import patch

import pytest

import request_credentials
from server import mcp


@pytest.mark.browser
def test_browser_user_token_flow_can_issue_bearer_and_call_mcp(
    page,
    live_server_url: str,
    mock_user_token_upstream,
    browser_account_cleanup,
    run_async,
) -> None:
    mocked = mock_user_token_upstream(
        domain="browser-user-token-domain",
        login="browser-doctor",
        password="Browser-Doctor-Pass-123",
        user_token="browser-user-token-secret",
    )
    account_email = "browser-user-token@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Browser-User-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    assert page.locator("h1").inner_text() == "Личный кабинет"
    assert page.get_by_test_id("integration-api-key").count() == 1

    page.get_by_test_id("auth-mode-user-token-radio").check()
    page.get_by_test_id("panel-user-token").wait_for(state="visible")

    assert page.get_by_test_id("panel-user-token").is_visible()
    assert page.get_by_test_id("panel-domain-api-key").is_hidden()

    page.get_by_test_id("integration-domain-user-token").fill(mocked.domain)
    page.get_by_test_id("integration-vm-login").fill(mocked.login)
    page.get_by_test_id("integration-vm-password").fill(mocked.password)
    page.get_by_test_id("integration-submit").click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()
    assert mocked.password not in page.content()
    assert mocked.user_token not in page.content()

    page.get_by_test_id("token-name").fill("Browser user token")
    page.get_by_test_id("token-expires-in-days").fill("7")
    page.get_by_test_id("token-submit").click()
    page.wait_for_load_state("networkidle")

    raw_token = page.get_by_test_id("issued-token-value").text_content()
    assert raw_token.startswith("vm_st_")
    assert mocked.password not in page.content()
    assert mocked.user_token not in page.content()

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_users", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
    assert mocked.billing_route.called
    assert mocked.token_auth_route.called
    assert mocked.validation_route.called
    assert any(request.url.path == "/token_auth.php" for request in mocked.token_exchange_requests)
    assert any(request.url.params["limit"] == "2" for request in mocked.validation_requests)
