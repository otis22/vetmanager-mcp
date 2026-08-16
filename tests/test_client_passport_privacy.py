"""Regression coverage for passport redaction in client output tools."""

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


_UPSTREAM_CLIENT = {
    "id": 42,
    "last_name": "Иванова",
    "first_name": "Анна",
    "email": "anna@example.test",
    "cell_phone": "+79990000000",
    "passport_series": "1234 567890",
    "custom_agent_field": "must be preserved",
}

_UPSTREAM_STAFF = {
    "id": 7,
    "first_name": "Анна",
    "position_id": 3,
    "email": "anna@example.test",
    "login": "anna.admin",
    "passwd": "0123456789abcdef0123456789abcdef",
    "last_change_pwd_date": "2026-08-01",
    "user_inn": "123456789012",
    "calc_percents": 25,
    "custom_invoice_context": "must be preserved",
}


def _runtime_patch():
    return patch_runtime_credentials(
        "testclinic",
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _assert_passport_redacted(client: dict) -> None:
    assert "passport_series" not in client
    assert client["id"] == _UPSTREAM_CLIENT["id"]
    assert client["email"] == _UPSTREAM_CLIENT["email"]
    assert client["custom_agent_field"] == _UPSTREAM_CLIENT["custom_agent_field"]


def _assert_staff_credentials_redacted(user: dict) -> None:
    for field in ("passwd", "login", "last_change_pwd_date", "user_inn", "calc_percents"):
        assert field not in user
    assert user["id"] == _UPSTREAM_STAFF["id"]
    assert user["first_name"] == _UPSTREAM_STAFF["first_name"]
    assert user["position_id"] == _UPSTREAM_STAFF["position_id"]
    assert user["email"] == _UPSTREAM_STAFF["email"]
    assert user["custom_invoice_context"] == _UPSTREAM_STAFF["custom_invoice_context"]


@pytest.mark.asyncio
async def test_get_clients_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"client": [_UPSTREAM_CLIENT], "totalCount": 1}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_clients", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"][0])


@pytest.mark.asyncio
async def test_get_clients_name_search_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"client": [_UPSTREAM_CLIENT], "totalCount": 1}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_clients", {"name": "Иванова"})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["client"][0])


@pytest.mark.asyncio
async def test_get_client_by_id_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_get_by_id(*args, **kwargs):
        return {"success": True, "data": _UPSTREAM_CLIENT}

    monkeypatch.setattr(client_module, "crud_get_by_id", fake_crud_get_by_id)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_client_by_id", {"client_id": 42})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"])


@pytest.mark.asyncio
async def test_get_debtors_redacts_passport_series(monkeypatch):
    import tools.client as client_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "client": [{**_UPSTREAM_CLIENT, "balance": "-100.00"}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_debtors", {})

    payload = result.structured_content or {}
    assert "passport_series" not in payload["debtors"][0]
    assert payload["debtors"][0]["id"] == _UPSTREAM_CLIENT["id"]


@pytest.mark.asyncio
async def test_get_pet_profile_redacts_owner_passport_series(monkeypatch):
    import tools.pet as pet_module

    async def fake_fetch_pet_profile(*args, **kwargs):
        return {"pet": {"id": 3}, "owner": _UPSTREAM_CLIENT}

    async def fake_instrument_call(*args, **kwargs):
        return await args[2]()

    monkeypatch.setattr(pet_module, "_fetch_pet_profile", fake_fetch_pet_profile)
    monkeypatch.setattr(pet_module, "_instrument_call", fake_instrument_call)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pet_profile", {"pet_id": 3})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["owner"])


@pytest.mark.asyncio
async def test_get_pets_redacts_nested_owner_passport_series(monkeypatch):
    import tools.pet as pet_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"pet": [{"id": 3, "owner": _UPSTREAM_CLIENT}], "totalCount": 1},
        }

    monkeypatch.setattr(pet_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pets", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["pet"][0]["owner"])


@pytest.mark.asyncio
async def test_get_admissions_redacts_nested_client_passport_series(monkeypatch):
    import tools.admission as admission_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "admission": [{"id": 4, "client": _UPSTREAM_CLIENT}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(admission_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_admissions", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["admission"][0]["client"])


@pytest.mark.asyncio
async def test_get_invoices_redacts_nested_client_passport_series(monkeypatch):
    import tools.invoice as invoice_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"invoice": [{"id": 5, "client": _UPSTREAM_CLIENT}], "totalCount": 1},
        }

    monkeypatch.setattr(invoice_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoices", {})

    payload = result.structured_content or {}
    _assert_passport_redacted(payload["data"]["invoice"][0]["client"])


@pytest.mark.asyncio
async def test_get_invoices_redacts_nested_doctor_credentials(monkeypatch):
    import tools.invoice as invoice_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {"invoice": [{"id": 5, "doctor": _UPSTREAM_STAFF}], "totalCount": 1},
        }

    monkeypatch.setattr(invoice_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoices", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["invoice"][0]["doctor"])


@pytest.mark.asyncio
async def test_get_hospitalizations_redacts_nested_doctor_credentials(monkeypatch):
    import tools.clinical as clinical_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "hospital": [{"id": 6, "doctor_data": _UPSTREAM_STAFF}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(clinical_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_hospitalizations", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["hospital"][0]["doctor_data"])


@pytest.mark.asyncio
async def test_get_cassa_closes_redacts_nested_closed_user_credentials(monkeypatch):
    import tools.finance as finance_module

    async def fake_crud_list(*args, **kwargs):
        return {
            "success": True,
            "data": {
                "cassaclose": [{"id": 8, "closedUser": _UPSTREAM_STAFF}],
                "totalCount": 1,
            },
        }

    monkeypatch.setattr(finance_module, "crud_list", fake_crud_list)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_cassa_closes", {})

    payload = result.structured_content or {}
    _assert_staff_credentials_redacted(payload["data"]["cassaclose"][0]["closedUser"])
