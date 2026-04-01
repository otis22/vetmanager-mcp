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
    page.locator('input[name="email"]').fill(account_email)
    page.locator('input[name="password"]').fill("Browser-User-Pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    assert page.locator("h1").inner_text() == "Личный кабинет"
    assert page.locator('input[name="api_key"]').count() == 1

    integration_form = page.locator('form[data-auth-wizard="true"]')
    integration_form.locator('input[name="auth_mode"][value="user_token"]').check()
    page.locator('[data-mode-panel="user_token"]').wait_for(state="visible")

    assert page.locator('[data-mode-panel="user_token"]').is_visible()
    assert page.locator('[data-mode-panel="domain_api_key"]').is_hidden()

    user_token_panel = integration_form.locator('[data-mode-panel="user_token"]')
    user_token_panel.locator('input[name="domain"]').fill(mocked.domain)
    user_token_panel.locator('input[name="vm_login"]').fill(mocked.login)
    user_token_panel.locator('input[name="vm_password"]').fill(mocked.password)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()
    assert mocked.password not in page.content()
    assert mocked.user_token not in page.content()

    page.locator('form[action="/account/tokens"] input[name="token_name"]').fill("Browser user token")
    page.locator('form[action="/account/tokens"] input[name="expires_in_days"]').fill("7")
    page.locator('form[action="/account/tokens"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    raw_token = page.locator("#issued-token-value").input_value()
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
