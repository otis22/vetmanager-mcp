"""Browser happy-path coverage for domain+api_key account onboarding."""
from unittest.mock import patch

import pytest

import auth.request as auth_request
from server import mcp


@pytest.mark.browser
def test_browser_domain_api_key_flow_can_issue_bearer_and_call_mcp(
    page,
    live_server_url: str,
    mock_domain_api_key_upstream,
    browser_account_cleanup,
    run_async,
) -> None:
    mocked = mock_domain_api_key_upstream(
        domain="browser-domain-api-key",
        api_key="browser-domain-api-key-secret",
    )
    account_email = "browser-domain-api@example.com"
    browser_account_cleanup.track_account_email(account_email)

    page.goto(f"{live_server_url}/register")
    page.get_by_test_id("register-email").fill(account_email)
    page.get_by_test_id("register-password").fill("Browser-Domain-Pass-123")
    page.get_by_test_id("register-submit").click()
    page.wait_for_load_state("networkidle")

    assert page.locator("h1").inner_text() == "Личный кабинет"
    assert page.get_by_test_id("integration-api-key").count() == 1
    assert page.get_by_test_id("panel-domain-api-key").is_visible()
    assert page.get_by_test_id("panel-user-token").is_hidden()

    page.get_by_test_id("integration-domain").fill(mocked.domain)
    page.get_by_test_id("integration-api-key").fill(mocked.api_key)
    page.get_by_test_id("integration-submit").click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()
    assert mocked.api_key not in page.content()

    page.get_by_test_id("token-name").fill("Browser API token")
    page.get_by_test_id("token-expires-in-days").fill("7")
    page.get_by_test_id("token-submit").click()
    page.wait_for_load_state("networkidle")

    raw_token = page.get_by_test_id("issued-token-value").text_content()
    assert raw_token.startswith("vm_st_")
    assert mocked.api_key not in page.content()

    with patch.object(
        auth_request,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
    assert mocked.billing_route.called
    assert mocked.validation_route.called
    assert any(request.url.params["limit"] == "2" for request in mocked.validation_requests)
