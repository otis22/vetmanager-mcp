"""Stage 331 — create-pet and medical-card inputs match Vetmanager."""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ValidationError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
BASE = "https://testclinic.vetmanager.cloud"


async def _call(tool: str, arguments: dict):
    headers, runtime = patch_runtime_credentials(
        DOMAIN, "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        return await mcp.call_tool(tool, arguments)


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


CREATE_CARD = {
    "patient_id": 5,
    "doctor_id": 3,
    "date_create": "2026-09-19",
    "clinic_id": 9,
    "admission_type": 3,
}


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("tool", "arguments"),
    [
        pytest.param("create_pet", {"alias": "S331", "owner_id": 1, "breed_id": 2}, id="pet-missing-type"),
        pytest.param("create_pet", {"alias": "S331", "owner_id": 1, "type_id": 1}, id="pet-missing-breed"),
        pytest.param("create_pet", {"alias": "S331", "owner_id": 1, "type_id": 0, "breed_id": 2}, id="pet-zero-type"),
        pytest.param("create_pet", {"alias": "S331", "owner_id": 1, "type_id": 1, "breed_id": 0}, id="pet-zero-breed"),
        pytest.param("create_medical_card", {k: v for k, v in CREATE_CARD.items() if k != "clinic_id"}, id="card-missing-clinic"),
        pytest.param("create_medical_card", {**CREATE_CARD, "clinic_id": 0}, id="card-zero-clinic"),
        pytest.param("create_medical_card", {**CREATE_CARD, "admission_type": "Первичный"}, id="create-admission-title"),
        pytest.param("create_medical_card", {**CREATE_CARD, "admission_type": "3"}, id="create-admission-string"),
        pytest.param("create_medical_card", {**CREATE_CARD, "admission_type": 0}, id="create-admission-zero"),
        pytest.param("create_medical_card", {**CREATE_CARD, "admission_type": -1}, id="create-admission-negative"),
        pytest.param("update_medical_card", {"card_id": 42, "admission_type": "Первичный"}, id="update-admission-title"),
        pytest.param("update_medical_card", {"card_id": 42, "admission_type": "4"}, id="update-admission-string"),
        pytest.param("update_medical_card", {"card_id": 42, "admission_type": 0}, id="update-admission-zero"),
        pytest.param("update_medical_card", {"card_id": 42, "admission_type": -1}, id="update-admission-negative"),
    ],
)
async def test_invalid_stage331_references_are_refused_before_io(tool, arguments):
    with pytest.raises(ValidationError):
        await _call(tool, arguments)
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card_sends_admission_type_as_json_integer():
    _billing_mock()
    route = respx.post(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(201, json={"data": {"id": 105}})
    )
    await _call("create_medical_card", CREATE_CARD)
    assert _body(route)["admission_type"] == 3
    assert type(_body(route)["admission_type"]) is int


@pytest.mark.asyncio
@respx.mock
async def test_update_medical_card_changes_admission_type_without_resetting_fields():
    _billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/42").mock(return_value=httpx.Response(
        200,
        json={"data": {"totalCount": 1, "medicalCards": {
            "id": 42, "patient_id": 7, "doctor_id": 8, "clinic_id": 9,
            "description": "keep upstream", "treatment": "keep upstream",
        }}},
    ))
    route = respx.put(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    await _call("update_medical_card", {"card_id": 42, "admission_type": 4})
    assert _body(route) == {
        "patient_id": 7, "doctor_id": 8, "clinic_id": 9, "admission_type": 4,
    }


@pytest.mark.asyncio
async def test_schemas_require_confirmed_ids_and_describe_catalogue_code():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    pet, card = tools["create_pet"], tools["create_medical_card"]
    assert {"alias", "owner_id", "type_id", "breed_id"} <= set(pet.inputSchema["required"])
    assert {"patient_id", "doctor_id", "date_create", "clinic_id"} <= set(card.inputSchema["required"])
    descriptions = f"{pet.description}\n{card.description}".lower()
    assert "0 if unknown" not in descriptions
    assert "0 = default" not in descriptions
    assert "catalogue code" in card.description.lower()
