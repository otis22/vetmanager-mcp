"""Regressions for Stage 221 clinical profile completeness."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


@pytest.mark.asyncio
@respx.mock
async def test_profile_exposes_fullness_and_resolved_diagnosis_titles():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/740").mock(return_value=httpx.Response(
        200, json={"data": {"pet": {"id": 740, "alias": "Муся"}}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 7, "medicalCards": [
            {"id": 7, "diagnos": "124", "weight": "3.9"},
            {"id": 1, "diagnos": "124", "weight": "5.2"},
        ]}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(return_value=httpx.Response(
        200, json={"data": {"diagnoses": [{"id": 124, "title": "Хроническая болезнь почек"}]}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        payload = (await mcp.call_tool("get_pet_profile", {"pet_id": 740})).structured_content
    assert payload["medical_cards_total"] == 7
    assert payload["medical_cards_returned"] == 2
    assert payload["medical_cards_truncated"] is True
    assert payload["diagnoses"] == ["Хроническая болезнь почек"]
    assert all(card["diagnosis_titles"] == ["Хроническая болезнь почек"] for card in payload["last_medical_cards"])


@pytest.mark.asyncio
@respx.mock
async def test_profile_empty_pet_is_explicit_not_found_without_fanout():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/999").mock(return_value=httpx.Response(200, json={"data": {"pet": []}}))
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        with pytest.raises(ToolError, match="Pet 999 not found"):
            await mcp.call_tool("get_pet_profile", {"pet_id": 999})


@pytest.mark.asyncio
@respx.mock
async def test_find_pets_by_alias_projects_candidates_without_owner_data():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 2, "pet": [{
            "id": 740, "alias": "Муся", "owner_id": 662, "type_id": 1,
            "breed_id": 1, "birthday": "2012-06-15", "status": "alive",
        }]}}
    ))
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        payload = (await mcp.call_tool("find_pets_by_alias", {"alias": "Муся"})).structured_content
    assert payload["data"]["totalCount"] == 2
    assert payload["has_more"] is True
    assert payload["data"]["pets"] == [{
        "id": 740, "alias": "Муся", "type_id": 1, "breed_id": 1,
        "birthday": "2012-06-15", "status": "alive",
    }]
