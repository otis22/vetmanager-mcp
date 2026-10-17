"""Stage 410: personal and non-personal pet-list values across access modes."""

from unittest.mock import AsyncMock

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


CLIENT = {
    "id": 42, "last_name": "Смирнова", "first_name": "Анна",
    "middle_name": "", "cell_phone": "+7 999 123-45-67",
    "email": "anna@example.test", "address": "ул. Мира, 1",
    "last_visit_date": "2024-12-15 14:30:00",
}
PET = {"id": 7, "alias": "Рекс", "owner_id": 42, "status": "alive",
       "note": "Анализ крови общий", "owner": CLIENT}


@pytest.mark.asyncio
async def test_pet_list_catalog_exposes_mask_and_final_doctor_value():
    exports = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    for name in ("get_pets", "get_inactive_pets", "find_pets_by_alias"):
        assert exports[name].inputSchema["properties"]["mask_contacts"]["default"] is False
    assert "[user:<doctor_id>:first_name]" in exports["get_inactive_pets"].description


async def _call(tool, arguments, *, depersonalized):
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", is_depersonalized=depersonalized,
    )
    with headers, runtime:
        return (await mcp.call_tool(tool, arguments)).structured_content


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
@pytest.mark.parametrize("masked", [False, True])
async def test_get_pets_contact_matrix(monkeypatch, depersonalized, masked):
    from tools import pet as module
    mocked = AsyncMock(return_value={"success": True, "data": {
        "pet": [PET], "totalCount": 1,
    }})
    monkeypatch.setattr(module, "crud_list", mocked)
    result = await _call("get_pets", {"limit": 1, "mask_contacts": masked},
                         depersonalized=depersonalized)
    row = result["data"]["pet"][0]
    assert row["client_id"] == 42 and row["alias"] == "Рекс"
    assert row["status"] == "alive" and row["note"] == "Анализ крови общий"
    assert row["owner"]["id"] == 42
    if masked:
        assert row["owner"]["cell_phone"] == "[redacted-phone]"
        assert row["owner"]["email"] == "[redacted-email]"
        assert row["owner"]["address"] == "[redacted-address]"
    elif depersonalized:
        assert row["owner"]["cell_phone"] != CLIENT["cell_phone"]
    else:
        assert row["owner"]["cell_phone"] == CLIENT["cell_phone"]
        assert row["owner"]["first_name"] == "Анна"
    assert "mask_contacts" not in mocked.call_args.kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
@pytest.mark.parametrize("masked", [False, True])
async def test_get_inactive_pets_contact_and_doctor_matrix(monkeypatch, depersonalized, masked):
    from tools import pet as module
    monkeypatch.setattr(module, "fetch_inactive_clients_page", AsyncMock(
        return_value=([CLIENT], "2024-01-01", "2024-12-31", 1),
    ))
    visited = {"id": 7, "alias": "Рекс", "owner_id": 42, "type_id": 1,
               "visit_source": "invoice", "visit_doctor_id": 8,
               "visit_doctor_name": "Иванов Иван"}
    monkeypatch.setattr(module, "find_pets_for_clients_last_visit", AsyncMock(
        return_value=[(CLIENT, [visited])],
    ))
    result = await _call("get_inactive_pets", {"limit": 1, "mask_contacts": masked},
                         depersonalized=depersonalized)
    row = result["inactive_pets"][0]
    assert row["id"] == 7 and row["client_id"] == 42
    assert row["alias"] == "Рекс" and row["visit_source"] == "invoice"
    assert row["last_visit_date"] == CLIENT["last_visit_date"]
    assert row["doctor_name"] == "[user:8:first_name]"
    if masked:
        assert row["owner_phone"] == "[redacted-phone]"
    elif depersonalized:
        assert row["owner_phone"] != CLIENT["cell_phone"]
    else:
        assert row["owner_phone"] == CLIENT["cell_phone"]
        assert row["owner_name"] == "Смирнова Анна"


@pytest.mark.asyncio
@pytest.mark.parametrize("depersonalized", [False, True])
@pytest.mark.parametrize("masked", [False, True])
@pytest.mark.parametrize("embedded", [False, True])
async def test_alias_owner_embedded_and_fallback_matrix(
    monkeypatch, depersonalized, masked, embedded,
):
    from tools import pet as module
    row = {key: value for key, value in PET.items() if key != "owner"}
    if embedded:
        row["owner"] = CLIENT
    monkeypatch.setattr(module, "crud_list", AsyncMock(return_value={
        "success": True, "data": {"pet": [row], "totalCount": 1},
    }))
    fallback = AsyncMock(return_value=(42, {"name": "Смирнова Анна",
                                            "phone": CLIENT["cell_phone"]}))
    monkeypatch.setattr(module, "_fetch_owner_summary", fallback)
    result = await _call("find_pets_by_alias", {"alias": "Рекс", "mask_contacts": masked},
                         depersonalized=depersonalized)
    candidate = result["data"]["pets"][0]
    assert candidate["id"] == 7 and candidate["client_id"] == 42
    assert candidate["alias"] == "Рекс" and candidate["status"] == "alive"
    assert candidate["owner"]["name"] != ""  # names remain usable or sanitized
    if masked:
        assert candidate["owner"]["phone"] == "[redacted-phone]"
    elif depersonalized:
        assert candidate["owner"]["phone"] != CLIENT["cell_phone"]
    else:
        assert candidate["owner"]["phone"] == CLIENT["cell_phone"]
    assert fallback.await_count == (0 if embedded else 1)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_owner", ["anna@example.test", [CLIENT]])
async def test_pet_mask_fails_closed_on_invalid_owner(monkeypatch, bad_owner):
    from tools import pet as module
    monkeypatch.setattr(module, "crud_list", AsyncMock(return_value={
        "success": True, "data": {"pet": [{**PET, "owner": bad_owner}]},
    }))
    with pytest.raises(Exception, match="Contact masking"):
        await _call("get_pets", {"mask_contacts": True}, depersonalized=False)


@pytest.mark.asyncio
@pytest.mark.parametrize("owner, expected", [
    (None, None),
    ({**CLIENT, "cell_phone": {"unexpected": "nested"}}, "[redacted-phone]"),
])
async def test_pet_mask_handles_nullable_or_malformed_contact(monkeypatch, owner, expected):
    from tools import pet as module
    monkeypatch.setattr(module, "crud_list", AsyncMock(return_value={
        "success": True, "data": {"pet": [{**PET, "owner": owner}]},
    }))
    result = await _call("get_pets", {"mask_contacts": True}, depersonalized=False)
    masked_owner = result["data"]["pet"][0]["owner"]
    assert (masked_owner if owner is None else masked_owner["cell_phone"]) == expected
