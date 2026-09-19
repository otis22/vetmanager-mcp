"""Stage 331 — create-pet and medical-card inputs match Vetmanager."""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ValidationError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def _runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


async def _call(tool: str, arguments: dict):
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        return await mcp.call_tool(tool, arguments)


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "arguments",
    [
        pytest.param({"alias": "Stage331", "owner_id": 1, "breed_id": 2}, id="missing-type"),
        pytest.param({"alias": "Stage331", "owner_id": 1, "type_id": 1}, id="missing-breed"),
        pytest.param(
            {"alias": "Stage331", "owner_id": 1, "type_id": 0, "breed_id": 2},
            id="zero-type",
        ),
        pytest.param(
            {"alias": "Stage331", "owner_id": 1, "type_id": 1, "breed_id": 0},
            id="zero-breed",
        ),
    ],
)
async def test_create_pet_refuses_missing_or_zero_reference_ids_before_io(arguments):
    with pytest.raises(ValidationError):
        await _call("create_pet", arguments)
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "clinic_id",
    [pytest.param(None, id="missing"), pytest.param(0, id="zero")],
)
async def test_create_medical_card_refuses_missing_or_zero_clinic_before_io(clinic_id):
    arguments = {
        "patient_id": 5,
        "doctor_id": 3,
        "date_create": "2026-09-19",
        "admission_type": 3,
    }
    if clinic_id is not None:
        arguments["clinic_id"] = clinic_id

    with pytest.raises(ValidationError):
        await _call("create_medical_card", arguments)
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "admission_type",
    [
        pytest.param("Первичный", id="title"),
        pytest.param("3", id="numeric-string"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
async def test_create_medical_card_refuses_non_positive_integer_admission_type_before_io(
    admission_type,
):
    with pytest.raises(ValidationError):
        await _call(
            "create_medical_card",
            {
                "patient_id": 5,
                "doctor_id": 3,
                "date_create": "2026-09-19",
                "clinic_id": 9,
                "admission_type": admission_type,
            },
        )
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "admission_type",
    [
        pytest.param("Первичный", id="title"),
        pytest.param("4", id="numeric-string"),
        pytest.param(0, id="zero"),
        pytest.param(-1, id="negative"),
    ],
)
async def test_update_medical_card_refuses_non_positive_integer_admission_type_before_io(
    admission_type,
):
    with pytest.raises(ValidationError):
        await _call(
            "update_medical_card",
            {"card_id": 42, "admission_type": admission_type},
        )
    assert not respx.calls


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card_sends_admission_type_as_json_integer():
    _billing_mock()
    route = respx.post(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(201, json={"data": {"id": 105}})
    )

    await _call(
        "create_medical_card",
        {
            "patient_id": 5,
            "doctor_id": 3,
            "date_create": "2026-09-19",
            "clinic_id": 9,
            "admission_type": 3,
        },
    )

    body = _body_of(route)
    assert body["admission_type"] == 3
    assert type(body["admission_type"]) is int


@pytest.mark.asyncio
@respx.mock
async def test_update_medical_card_changes_admission_type_without_resetting_other_fields():
    _billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "medicalCards": {
                        "id": 42,
                        "patient_id": 7,
                        "doctor_id": 8,
                        "clinic_id": 9,
                        "description": "keep upstream",
                        "treatment": "keep upstream",
                    },
                }
            },
        )
    )
    route = respx.put(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )

    await _call("update_medical_card", {"card_id": 42, "admission_type": 4})

    assert _body_of(route) == {
        "patient_id": 7,
        "doctor_id": 8,
        "clinic_id": 9,
        "admission_type": 4,
    }


@pytest.mark.asyncio
async def test_create_tool_schemas_require_confirmed_ids_and_describe_catalogue_code():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    pet = tools["create_pet"]
    card = tools["create_medical_card"]

    assert {"alias", "owner_id", "type_id", "breed_id"} <= set(
        pet.inputSchema["required"]
    )
    assert {"patient_id", "doctor_id", "date_create", "clinic_id"} <= set(
        card.inputSchema["required"]
    )

    descriptions = f"{pet.description}\n{card.description}".lower()
    assert "0 if unknown" not in descriptions
    assert "0 = default" not in descriptions
    assert "catalogue code" in card.description.lower()
