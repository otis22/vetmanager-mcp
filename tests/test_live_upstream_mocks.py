"""Regression coverage for deterministic upstream mocks over live browser HTTP."""

import pytest


@pytest.mark.browser
def test_live_http_domain_api_key_flow_uses_deterministic_upstream_mocks(
    page,
    live_server_url: str,
    mock_domain_api_key_upstream,
) -> None:
    mocked = mock_domain_api_key_upstream(
        domain="browser-api-key-clinic",
        api_key="browser-api-key-secret",
    )

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill("browser-api@example.com")
    page.locator('input[name="password"]').fill("Browser-Pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    page.goto(f"{live_server_url}/login")
    page.locator('input[name="email"]').fill("browser-api@example.com")
    page.locator('input[name="password"]').fill("Browser-Pass-123")
    page.locator('form[action="/login"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    integration_form = page.locator('form[data-auth-wizard="true"]')
    api_panel = integration_form.locator('[data-mode-panel="domain_api_key"]')
    api_panel.locator('input[name="domain"]').fill(mocked.domain)
    api_panel.locator('input[name="api_key"]').fill(mocked.api_key)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    html = page.content()
    assert "Vetmanager integration saved successfully." in html
    assert mocked.api_key not in html
    assert mocked.billing_route.called
    assert mocked.validation_route.called
    assert len(mocked.validation_requests) >= 1

    validation_request = mocked.validation_requests[-1]
    assert validation_request.headers["X-REST-API-KEY"] == mocked.api_key
    assert validation_request.url.path == "/rest/api/client"
    assert validation_request.url.params["limit"] == "1"
    assert validation_request.url.params["offset"] == "0"


@pytest.mark.browser
def test_live_http_user_token_flow_uses_deterministic_upstream_mocks(
    page,
    live_server_url: str,
    mock_user_token_upstream,
) -> None:
    mocked = mock_user_token_upstream(
        domain="browser-user-token-clinic",
        login="browser-doctor",
        password="browser-password-123",
        user_token="browser-issued-user-token",
    )

    page.goto(f"{live_server_url}/register")
    page.locator('input[name="email"]').fill("browser-user@example.com")
    page.locator('input[name="password"]').fill("Browser-Pass-123")
    page.locator('form[action="/register"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    page.goto(f"{live_server_url}/login")
    page.locator('input[name="email"]').fill("browser-user@example.com")
    page.locator('input[name="password"]').fill("Browser-Pass-123")
    page.locator('form[action="/login"] button[type="submit"]').click()
    page.wait_for_load_state("networkidle")

    integration_form = page.locator('form[data-auth-wizard="true"]')
    integration_form.locator('input[name="auth_mode"][value="user_token"]').check()
    page.locator('[data-mode-panel="user_token"]').wait_for(state="visible")
    user_panel = integration_form.locator('[data-mode-panel="user_token"]')
    user_panel.locator('input[name="domain"]').fill(mocked.domain)
    user_panel.locator('input[name="vm_login"]').fill(mocked.login)
    user_panel.locator('input[name="vm_password"]').fill(mocked.password)
    integration_form.locator('button[type="submit"]').first.click()
    page.wait_for_load_state("networkidle")

    html = page.content()
    assert "Vetmanager integration saved successfully." in html
    assert mocked.user_token not in html
    assert mocked.password not in html
    assert mocked.billing_route.called
    assert mocked.token_auth_route.called
    assert mocked.validation_route.called
    assert len(mocked.token_exchange_requests) == 1
    assert len(mocked.validation_requests) >= 1

    token_exchange_request = mocked.token_exchange_requests[0]
    validation_request = mocked.validation_requests[-1]

    assert token_exchange_request.url.path == "/token_auth.php"
    assert token_exchange_request.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert "x-rest-api-key" not in {key.lower() for key in token_exchange_request.headers}
    assert b'name="app_name"' in token_exchange_request.content
    assert b"vetmanager-mcp" in token_exchange_request.content
    assert validation_request.headers["X-USER-TOKEN"] == mocked.user_token
    assert validation_request.headers["X-APP-NAME"] == mocked.app_name
    assert validation_request.url.path == "/rest/api/user"
    assert validation_request.url.params["limit"] == "1"
    assert validation_request.url.params["offset"] == "0"
