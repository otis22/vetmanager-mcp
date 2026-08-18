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
    assert payload["unresolved_diagnosis_ids"] == []
    assert payload["diagnoses_reference"] == {
        "returned": 1, "total_known": False, "pagination_supported": False,
    }
    assert all(card["diagnosis_titles"] == ["Хроническая болезнь почек"] for card in payload["last_medical_cards"])


@pytest.mark.asyncio
@respx.mock
async def test_profile_makes_unresolved_diagnosis_id_explicit():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/740").mock(return_value=httpx.Response(
        200, json={"data": {"pet": {"id": 740, "alias": "Муся"}}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 1, "medicalCards": [{"id": 1, "diagnos": "999"}]}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": {"diagnoses": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        payload = (await mcp.call_tool("get_pet_profile", {"pet_id": 740})).structured_content
    assert payload["unresolved_diagnosis_ids"] == ["999"]
    assert payload["last_medical_cards"][0]["unresolved_diagnosis_ids"] == ["999"]


@pytest.mark.asyncio
@respx.mock
async def test_profile_does_not_treat_absent_diagnosis_as_unresolved():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/748").mock(return_value=httpx.Response(
        200, json={"data": {"pet": {"id": 748, "alias": "Тимоша"}}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 5, "medicalCards": [
            {"id": 1, "diagnos": 0},
            {"id": 2, "diagnos": "0"},
            {"id": 3, "diagnos": ""},
            {"id": 4},
            {"id": 5, "diagnos": "999"},
        ]}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": {"diagnoses": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        payload = (await mcp.call_tool("get_pet_profile", {"pet_id": 748})).structured_content

    assert payload["unresolved_diagnosis_ids"] == ["999"]
    assert [card["unresolved_diagnosis_ids"] for card in payload["last_medical_cards"]] == [
        [], [], [], [], ["999"],
    ]


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
async def test_find_pets_by_alias_returns_owner_context_for_disambiguation():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 2, "pet": [{
            "id": 740, "alias": "Муся", "owner_id": 662, "type_id": 1,
            "breed_id": 1, "birthday": "2012-06-15", "status": "alive",
        }]}}
    ))
    respx.get(f"{BASE}/rest/api/client/662").mock(return_value=httpx.Response(
        200, json={"data": {"client": {
            "id": 662, "last_name": "Иванова", "first_name": "Анна",
            "middle_name": "Сергеевна", "cell_phone": "+79990000000",
            "passport_series": "1234 567890",
        }}}
    ))
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers, runtime:
        payload = (await mcp.call_tool("find_pets_by_alias", {"alias": "Муся"})).structured_content
    assert payload["data"]["totalCount"] == 2
    assert payload["has_more"] is True
    assert payload["data"]["pets"] == [{
        "id": 740, "alias": "Муся", "owner_id": 662, "type_id": 1,
        "breed_id": 1, "birthday": "2012-06-15", "status": "alive",
        "owner": {"name": "Иванова Анна Сергеевна", "phone": "+79990000000"},
    }]


@pytest.mark.asyncio
async def test_find_pets_by_alias_uses_global_depersonalization_wrapper(monkeypatch):
    import tools.pet as pet_module

    async def fake_crud_list(*args, **kwargs):
        return {"success": True, "data": {"pet": [{
            "id": 740, "alias": "Муся", "owner_id": 662, "type_id": 1,
            "breed_id": 1, "birthday": "2012-06-15", "status": "alive",
        }], "totalCount": 1}}

    async def fake_get(self, path, **kwargs):
        assert path == "/rest/api/client/662"
        return {"data": {"client": {
            "id": 662, "last_name": "Иванова", "first_name": "Анна",
            "cell_phone": "+79990000000", "passport_series": "1234 567890",
        }}}

    monkeypatch.setattr(pet_module, "crud_list", fake_crud_list)
    monkeypatch.setattr(pet_module.VetmanagerClient, "get", fake_get)
    headers, runtime = patch_runtime_credentials(DOMAIN, API_KEY, is_depersonalized=True)
    with headers, runtime:
        payload = (await mcp.call_tool("find_pets_by_alias", {"alias": "Муся"})).structured_content

    candidate = payload["data"]["pets"][0]
    assert candidate["owner_id"] == 662
    assert candidate["owner"] == {"name": "[redacted-name]", "phone": "[redacted-phone]"}
    assert "passport_series" not in candidate["owner"]
