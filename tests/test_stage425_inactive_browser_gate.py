"""Stage 425: an existing browser session loses access when its account is disabled."""

from pathlib import Path
import ast

import httpx
import pytest
import respx

import storage
from server import mcp
from storage_models import ACCOUNT_STATUS_INACTIVE, Account, VetmanagerConnection
from tests.test_web_auth import (
    TEST_ENCRYPTION_KEY,
    _extract_csrf_token,
    _post_with_csrf,
    _prepare_web_db,
)
from web_auth import SESSION_COOKIE_NAME, register_account
from web import _is_protected_browser_route


PROTECTED_ROUTES = {
    ("GET", "/account"),
    ("POST", "/account/agent-feedback"),
    ("POST", "/account/integration"),
    ("POST", "/account/integration/reauth"),
    ("POST", "/account/tokens"),
    ("POST", "/account/tokens/{token_id:int}/revoke"),
    ("POST", "/account/oauth-grants/{grant_id:int}/revoke"),
    ("POST", "/account/telemetry/token-copied"),
    ("POST", "/account/telemetry/motivator-shown"),
    ("POST", "/account/telemetry/example-copied"),
    ("GET", "/account/activation-status"),
    ("GET", "/oauth/authorize"),
    ("POST", "/oauth/authorize/consent"),
}


def _registered_browser_routes() -> set[tuple[str, str]]:
    """Independently inventory route declarations, including future cookie users."""
    found = set()
    for name in ("web_routes_account.py", "web_routes_oauth.py"):
        tree = ast.parse((Path(__file__).resolve().parents[1] / name).read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Name):
                    continue
                if decorator.func.id != "observed_route":
                    continue
                path_node = decorator.args[1]
                if not isinstance(path_node, ast.Constant) or not isinstance(path_node.value, str):
                    continue
                path = path_node.value
                reads_cookie = any(
                    isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Name)
                    and call.func.id == "get_account_id_from_request"
                    for call in ast.walk(node)
                )
                if name == "web_routes_oauth.py" and not reads_cookie:
                    continue
                methods = next(keyword.value for keyword in decorator.keywords if keyword.arg == "methods")
                for method in ast.literal_eval(methods):
                    found.add((method, path))
    return found


def test_browser_route_inventory_matches_gate() -> None:
    assert _registered_browser_routes() == PROTECTED_ROUTES
    root = Path(__file__).resolve().parents[1]
    cookie_consumers = {
        source.name
        for source in root.glob("*.py")
        if any(
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "get_account_id_from_request"
            for call in ast.walk(ast.parse(source.read_text()))
        )
    }
    assert cookie_consumers == {"web_routes_account.py", "web_routes_oauth.py"}
    assert all(_is_protected_browser_route(path) for _, path in PROTECTED_ROUTES)
    for path in ("/login", "/oauth/token", "/mcp", "/accounting"):
        assert not _is_protected_browser_route(path)


@pytest.mark.asyncio
async def test_all_browser_routes_refuse_inactive_cookie(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    async with storage.get_session_factory()() as session:
        await register_account(session, email="routes@example.com", password="Strong-Pass-123")
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await _post_with_csrf(
            client, "/login", {"email": "routes@example.com", "password": "Strong-Pass-123"}
        )
        assert login.status_code == 303
        cookie = client.cookies[SESSION_COOKIE_NAME]
        async with storage.get_session_factory()() as session:
            account = await session.get(Account, 1)
            account.status = ACCOUNT_STATUS_INACTIVE
            await session.commit()
        for method, template in sorted(PROTECTED_ROUTES):
            path = template.replace("{token_id:int}", "999").replace("{grant_id:int}", "999")
            client.cookies.clear()
            response = await client.request(
                method, path, headers={"Cookie": f"{SESSION_COOKIE_NAME}={cookie}"}
            )
            assert response.status_code == 403, (method, path, response.status_code)
            assert f"{SESSION_COOKIE_NAME}=" in response.headers["set-cookie"]
            assert "Max-Age=0" in response.headers["set-cookie"]
            assert "no-store" in response.headers["cache-control"]
            if path.startswith("/oauth/authorize"):
                assert "location" not in response.headers
            if path.startswith("/account/telemetry/") or path == "/account/activation-status":
                assert response.json()["error"] == "account_inactive"
            else:
                assert "Аккаунт отключён" in response.text
    await engine.dispose()
    storage.reset_storage_state()


@pytest.mark.asyncio
@respx.mock
async def test_existing_inactive_session_cannot_read_dashboard_or_save_integration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://clinic-a.vetmanager.cloud"}})
    )
    respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    app = mcp.http_app(path="/mcp", transport="streamable-http")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as read_client, \
        httpx.AsyncClient(transport=transport, base_url="http://testserver") as write_client:
        registration = await _post_with_csrf(
            read_client, "/register",
            {"email": "disabled@example.com", "password": "Strong-Pass-123"},
        )
        assert registration.status_code == 303
        login = await _post_with_csrf(
            write_client, "/login",
            {"email": "disabled@example.com", "password": "Strong-Pass-123"},
        )
        assert login.status_code == 303
        assert SESSION_COOKIE_NAME in read_client.cookies
        assert SESSION_COOKIE_NAME in write_client.cookies
        csrf = _extract_csrf_token((await write_client.get("/account")).text)

        async with storage.get_session_factory()() as session:
            account = await session.get(Account, 1)
            account.status = ACCOUNT_STATUS_INACTIVE
            await session.commit()

        dashboard = await read_client.get("/account")
        mutation = await write_client.post(
            "/account/integration",
            data={
                "csrf_token": csrf,
                "auth_mode": "domain_api_key",
                "domain": "clinic-a",
                "api_key": "secret-key",
            },
        )

    print(
        f"stage425 local web: register={registration.status_code} login={login.status_code} "
        f"dashboard={dashboard.status_code} integration={mutation.status_code}"
    )
    assert dashboard.status_code == 403
    assert "Аккаунт отключён" in dashboard.text
    assert "Обратитесь к администратору" in dashboard.text
    assert SESSION_COOKIE_NAME not in read_client.cookies
    assert mutation.status_code == 403
    assert SESSION_COOKIE_NAME not in write_client.cookies
    async with storage.get_session_factory()() as session:
        assert await session.get(VetmanagerConnection, 1) is None
    await engine.dispose()
    storage.reset_storage_state()
