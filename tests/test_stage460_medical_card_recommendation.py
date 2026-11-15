"""Stage 460: public recommendation projection from the REST spelling."""

import pytest

from depersonalization import REDACTED_PHONE
from exceptions import ToolInputError
from list_projection import project_list_result, selected_fields
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient


_TOOLS = ("get_medical_cards", "get_medical_cards_by_date", "get_medical_cards_by_client_id")
_RAW = "Повторить осмотр. Позвонить +7 (916) 123-45-67 владельцу."
_CLEAN = f"Повторить осмотр. Позвонить {REDACTED_PHONE} владельцу."


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", _TOOLS)
async def test_mcp_recommendation_projection_and_full_response(monkeypatch, tool_name):
    async def get(_self, path, **_kwargs):
        if path == "/rest/api/pet":
            return {"data": {"pet": [{"id": 2, "owner_id": 3, "alias": "Test pet"}],
                             "totalCount": 1}}
        assert path == "/rest/api/MedicalCards"
        return {"success": True, "data": {"medicalCards": [{
            "id": 7, "patient_id": 2, "description": "Осмотр без осложнений.",
            "recomendation": _RAW, "doctor_id": 4,
        }], "totalCount": 1}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    args = {
        "get_medical_cards": {"pet_id": 2},
        "get_medical_cards_by_date": {"date": "2026-11-01"},
        "get_medical_cards_by_client_id": {"client_id": 3},
    }[tool_name]
    headers, runtime = patch_runtime_credentials("testclinic", "mock-key", is_depersonalized=True)
    with headers, runtime:
        projected = await mcp.call_tool(tool_name, {**args, "fields": ["id", "recommendation"]})
        description = await mcp.call_tool(tool_name, {**args, "fields": ["id", "description"]})
        full = await mcp.call_tool(tool_name, args)
    def row(response):
        body = response.structured_content
        return (body.get("data", body).get("medicalCards") or body.get("medical_cards"))[0]

    assert not projected.is_error
    assert row(projected) == {"id": 7, "recommendation": _CLEAN}
    assert row(description) == {"id": 7, "description": "Осмотр без осложнений."}
    assert row(full)["recomendation"] == _CLEAN
    assert "recommendation" not in row(full)
    assert row(full)["pet_id"] == 2


@pytest.mark.parametrize("tool_name", _TOOLS)
def test_existing_rest_spelling_stays_unpublished_in_fields(tool_name):
    with pytest.raises(ToolInputError):
        selected_fields(tool_name, ["id", "recomendation"], False)


@pytest.mark.parametrize("canonical", ["explicit", None, ""])
def test_explicit_public_key_wins_even_if_empty(canonical):
    response = {"success": True, "data": {"medicalCards": [{
        "id": 7, "recommendation": canonical, "recomendation": "legacy",
    }], "totalCount": 1}}
    actual = project_list_result(response, "get_medical_cards", ("recommendation",))
    assert actual["data"]["medicalCards"] == [{"recommendation": canonical}]


def test_other_projection_does_not_translate_recommendation():
    response = {"success": True, "data": {"invoiceDocument": [{
        "id": 7, "recomendation": "legacy",
    }], "totalCount": 1}}
    actual = project_list_result(response, "get_invoice_documents_by_period", ("recommendation",))
    assert actual["data"]["invoiceDocument"] == [{}]
