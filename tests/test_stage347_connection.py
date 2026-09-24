"""Guards for the complete clinic connection flow."""

import asyncio
import logging

import httpx
import pytest
import respx

import vetmanager_connection_service as service
from exceptions import VetmanagerError, VetmanagerTimeoutError
from service_metrics import reset_service_metrics, snapshot_service_metrics
from storage_models import VetmanagerConnection
from web_routes_account import _integration_error_text


def test_redirect_and_flow_timeout_have_actionable_form_errors():
    redirect = _integration_error_text(
        VetmanagerError("Vetmanager connection test redirected; check clinic address.", status_code=302)
    )
    timeout = _integration_error_text(
        VetmanagerTimeoutError("Vetmanager connection timed out during token creation or validation.")
    )
    assert "Проверьте поддомен" in redirect
    assert "Токен мог быть создан" in timeout


@pytest.mark.asyncio
async def test_saved_connection_redirect_shows_address_hint(monkeypatch):
    connection = VetmanagerConnection(
        id=77, account_id=1, auth_mode="domain_api_key", status="active", domain="clinic",
    )
    key = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
    connection.set_credentials({"domain": "clinic", "api_key": "key"}, encryption_key=key)

    async def redirected(*args, **kwargs):
        raise VetmanagerError("Vetmanager connection test redirected; check clinic address.", status_code=302)

    monkeypatch.setattr(service, "validate_domain_api_key_connection", redirected)
    status, reason = await service.evaluate_connection_health(connection, encryption_key=key)
    assert status == "unknown"
    assert "clinic address" in reason


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("method,path,call", [
    ("GET", "/rest/api/client", "api_key"),
    ("GET", "/rest/api/user", "user_token"),
    ("POST", "/token_auth.php", "exchange"),
])
async def test_redirect_is_not_success(method, path, call, caplog):
    domain = "stage347-clinic"
    host = f"https://{domain}.vetmanager.cloud"
    respx.get(f"https://billing-api.vetmanager.cloud/host/{domain}").mock(
        return_value=httpx.Response(200, json={"data": {"url": host}})
    )
    route = respx.request(method, host + path).mock(
        return_value=httpx.Response(302, headers={"Location": "https://unsafe.example/secret"})
    )
    reset_service_metrics()
    with caplog.at_level(logging.INFO, logger="vetmanager.runtime"):
        with pytest.raises(VetmanagerError) as caught:
            if call == "api_key":
                await service.validate_domain_api_key_connection(domain, "key")
            elif call == "user_token":
                await service.validate_user_token_connection(domain, "token")
            else:
                await service.exchange_user_token(domain, login="doctor", password="secret")
    assert caught.value.status_code == 302
    assert route.call_count == 1
    assert "unsafe.example" not in caplog.text
    assert "secret" not in caplog.text
    metrics = snapshot_service_metrics()
    target = "vetmanager_token_auth" if call == "exchange" else "vetmanager_api_probe"
    assert metrics["upstream_requests_total"].get(f"{target}|success", 0) == 0
    assert metrics["upstream_requests_total"][f"{target}|error"] == 1


@pytest.mark.asyncio
async def test_shared_login_prepare_has_one_budget_and_never_saves_after_timeout(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage347.db")
    monkeypatch.setattr(service, "CONNECTION_FLOW_BUDGET_SECONDS", 0.02, raising=False)
    token_issues = 0
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def slow_exchange(*args, **kwargs):
        nonlocal token_issues
        token_issues += 1
        started.set()
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()
        return "https://clinic.vetmanager.cloud", "token"

    monkeypatch.setattr(service, "exchange_user_token", slow_exchange)

    async def save():
        async with session_factory() as session:
            return await service.save_user_login_password_connection(
                session, account_id=1, domain="clinic", login="doctor",
                password="secret", encryption_key="2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA=",
            )

    first = asyncio.create_task(save())
    await started.wait()
    second = asyncio.create_task(save())
    results = await asyncio.wait_for(asyncio.gather(first, second, return_exceptions=True), 1)
    assert all(isinstance(item, VetmanagerTimeoutError) for item in results)
    assert token_issues == 1
    assert cancelled.is_set()
    async with session_factory() as session:
        assert await session.get(VetmanagerConnection, 1) is None


@pytest.mark.asyncio
async def test_login_budget_covers_exchange_and_validation_together(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage347-serial.db")
    monkeypatch.setattr(service, "CONNECTION_FLOW_BUDGET_SECONDS", 0.03)
    calls = []

    async def exchange(*args, **kwargs):
        calls.append("post")
        await asyncio.sleep(0.02)
        return "https://clinic.vetmanager.cloud", "token"

    async def validate(*args, **kwargs):
        calls.append("get")
        await asyncio.sleep(0.02)

    monkeypatch.setattr(service, "exchange_user_token", exchange)
    monkeypatch.setattr(service, "validate_user_token_connection", validate)
    async with session_factory() as session:
        with pytest.raises(VetmanagerTimeoutError):
            await service.save_user_login_password_connection(
                session, account_id=1, domain="clinic", login="doctor",
                password="secret", encryption_key="2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA=",
            )
    assert calls == ["post", "get"]
    async with session_factory() as session:
        assert await session.get(VetmanagerConnection, 1) is None
