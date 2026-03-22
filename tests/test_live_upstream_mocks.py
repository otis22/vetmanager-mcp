"""Regression coverage for deterministic upstream mocks over live HTTP."""

import re

import httpx


CSRF_RE = re.compile(r'name="csrf_token" value="([^"]+)"')


def _extract_csrf_token(html: str) -> str:
    match = CSRF_RE.search(html)
    assert match is not None
    return match.group(1)


def _post_with_csrf(
    client: httpx.Client,
    path: str,
    data: dict[str, str],
    *,
    page_path: str | None = None,
) -> httpx.Response:
    csrf_page = client.get(page_path or path)
    token = _extract_csrf_token(csrf_page.text)
    request_data = dict(data)
    request_data["csrf_token"] = token
    return client.post(path, data=request_data, follow_redirects=True)


def test_live_http_domain_api_key_flow_uses_deterministic_upstream_mocks(
    live_server_url: str,
    mock_domain_api_key_upstream,
) -> None:
    mocked = mock_domain_api_key_upstream(
        domain="browser-api-key-clinic",
        api_key="browser-api-key-secret",
    )

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=10.0) as client:
        register = _post_with_csrf(
            client,
            "/register",
            data={"email": "browser-api@example.com", "password": "browser-pass-123"},
        )
        assert register.status_code == 200

        login = _post_with_csrf(
            client,
            "/login",
            data={"email": "browser-api@example.com", "password": "browser-pass-123"},
        )
        assert login.status_code == 200

        response = _post_with_csrf(
            client,
            "/account/integration",
            data={
                "auth_mode": "domain_api_key",
                "domain": mocked.domain,
                "api_key": mocked.api_key,
            },
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Vetmanager integration saved successfully." in response.text
    assert mocked.api_key not in response.text
    assert mocked.billing_route.called
    assert mocked.validation_route.called
    assert len(mocked.validation_requests) >= 1

    validation_request = mocked.validation_requests[-1]
    assert validation_request.headers["X-REST-API-KEY"] == mocked.api_key
    assert validation_request.url.path == "/rest/api/client"
    assert validation_request.url.params["limit"] == "1"
    assert validation_request.url.params["offset"] == "0"


def test_live_http_user_token_flow_uses_deterministic_upstream_mocks(
    live_server_url: str,
    mock_user_token_upstream,
) -> None:
    mocked = mock_user_token_upstream(
        domain="browser-user-token-clinic",
        login="browser-doctor",
        password="browser-password-123",
        user_token="browser-issued-user-token",
    )

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=10.0) as client:
        register = _post_with_csrf(
            client,
            "/register",
            data={"email": "browser-user@example.com", "password": "browser-pass-123"},
        )
        assert register.status_code == 200

        login = _post_with_csrf(
            client,
            "/login",
            data={"email": "browser-user@example.com", "password": "browser-pass-123"},
        )
        assert login.status_code == 200

        response = _post_with_csrf(
            client,
            "/account/integration",
            data={
                "auth_mode": "user_token",
                "domain": mocked.domain,
                "vm_login": mocked.login,
                "vm_password": mocked.password,
            },
            page_path="/account",
        )

    assert response.status_code == 200
    assert "Vetmanager integration saved successfully." in response.text
    assert mocked.user_token not in response.text
    assert mocked.password not in response.text
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
    assert validation_request.headers["X-REST-API-KEY"] == mocked.user_token
    assert validation_request.url.path == "/rest/api/user"
    assert validation_request.url.params["limit"] == "1"
    assert validation_request.url.params["offset"] == "0"
