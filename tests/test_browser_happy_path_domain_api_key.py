"""Browser happy-path coverage for domain+api_key account onboarding."""
from unittest.mock import patch

import pytest

import request_credentials
from server import mcp


@pytest.mark.browser
def test_browser_domain_api_key_flow_can_issue_bearer_and_call_mcp(
    page,
    live_server_url: str,
    mock_domain_api_key_upstream,
    run_async,
) -> None:
    mocked = mock_domain_api_key_upstream(
        domain="browser-domain-api-key",
        api_key="browser-domain-api-key-secret",
    )

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill("browser-domain-api@example.com")
    page.locator('input[name="password"]').fill("browser-domain-pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    assert page.locator("h1").inner_text() == "Личный кабинет"
    assert page.locator('input[name="api_key"]').count() == 1
    assert page.locator('[data-mode-panel="domain_api_key"]').is_visible()
    assert page.locator('[data-mode-panel="user_token"]').is_hidden()

    integration_form = page.locator('form[data-auth-wizard="true"]')
    domain_api_key_panel = integration_form.locator('[data-mode-panel="domain_api_key"]')
    domain_api_key_panel.locator('input[name="domain"]').fill(mocked.domain)
    domain_api_key_panel.locator('input[name="api_key"]').fill(mocked.api_key)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    assert "Vetmanager integration saved successfully." in page.content()
    assert mocked.api_key not in page.content()

    page.locator('form[action="/account/tokens"] input[name="token_name"]').fill("Browser API token")
    page.locator('form[action="/account/tokens"] input[name="expires_in_days"]').fill("7")
    page.locator('form[action="/account/tokens"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    raw_token = page.locator("#issued-token-value").input_value()
    assert raw_token.startswith("vm_st_")
    assert mocked.api_key not in page.content()

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"authorization": f"Bearer {raw_token}"},
    ):
        result = run_async(mcp.call_tool("get_clients", {"limit": 2, "offset": 0}))

    assert result.structured_content is not None
    assert "data" in result.structured_content
    assert mocked.billing_route.called
    assert mocked.validation_route.called
    assert any(request.url.params["limit"] == "2" for request in mocked.validation_requests)
