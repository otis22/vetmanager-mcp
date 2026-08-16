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
