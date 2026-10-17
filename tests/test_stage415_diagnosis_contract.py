"""Stage 415: live feedback contract retained after stage 391."""

import pytest
import httpx
import respx

from resources.pet_profile import _diagnosis_titles
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.asyncio
@respx.mock
async def test_profile_has_diagnoses_with_json_and_empty_catalog():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": base}})
    )
    respx.get(f"{base}/rest/api/pet/740").mock(
        return_value=httpx.Response(200, json={"data": {"pet": {"id": 740}}})
    )
    respx.get(f"{base}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 1, "medicalCards": [{
            "id": 7, "diagnos": '[{"id":123,"type":1},{"id":456,"type":2}]',
            "diagnos_text": "Первый;\nВторой",
            "diagnos_type_text": "Первый (основной);\nВторой (сопутствующий)",
        }]}}
    ))
    respx.get(f"{base}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": {"diagnoses": []}})
    )
    respx.get(f"{base}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    respx.get(f"{base}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"invoice": []}})
    )
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        payload = (await mcp.call_tool("get_pet_profile", {"pet_id": 740})).structured_content
    assert payload["diagnoses"] == ["Первый", "Второй"]
    assert payload["unresolved_diagnosis_ids"] == ["123", "456"]
    assert payload["last_medical_cards"][0]["diagnosis_references"] == [
        {"id": "123", "type": 1}, {"id": "456", "type": 2},
    ]


def test_json_references_keep_titles_when_catalog_is_empty():
    card = {
        "diagnos": '[{"id":123,"type":1},{"id":456,"type":2}]',
        "diagnos_text": "Первый;\nВторой",
        "diagnos_type_text": "Первый (основной);\nВторой (сопутствующий)",
    }
    assert _diagnosis_titles(card, {}) == (
        ["Первый", "Второй"], ["123", "456"],
        [{"id": "123", "type": 1}, {"id": "456", "type": 2}],
    )


@pytest.mark.parametrize("raw, expected", [
    ("123", (["Первый"], [], [])),
    ("", ([], [], [])),
    ("[]", ([], [], [])),
    ('[{"id":123,"type":1}', ([], ['[{"id":123,"type":1}'], [])),
])
def test_legacy_empty_and_malformed_forms(raw, expected):
    assert _diagnosis_titles({"diagnos": raw}, {"123": "Первый"}) == expected
