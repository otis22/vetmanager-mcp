"""Regression for serialized diagnosis references in clinical cards (stage 391)."""

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


BASE = "https://testclinic.vetmanager.cloud"


@pytest.mark.asyncio
@respx.mock
async def test_profile_decodes_json_diagnosis_references_and_card_text():
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/pet/740").mock(
        return_value=httpx.Response(200, json={"data": {"pet": {"id": 740}}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=httpx.Response(
        200, json={"data": {"totalCount": 1, "medicalCards": [{
            "id": 7, "diagnos": '[{"id":124,"type":1},{"id":999,"type":2}]',
            "diagnos_text": "Первый диагноз;\nВторой диагноз",
            "diagnos_type_text": "Первый диагноз (основной);\nВторой диагноз (сопутствующий)",
        }]}}
    ))
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": {"diagnoses": [
            {"id": 124, "title": "Первый диагноз"},
        ]}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"invoice": []}})
    )
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime:
        payload = (await mcp.call_tool("get_pet_profile", {"pet_id": 740})).structured_content

    card = payload["last_medical_cards"][0]
    assert card["diagnosis_references"] == [
        {"id": "124", "type": 1}, {"id": "999", "type": 2},
    ]
    assert card["diagnosis_titles"] == ["Первый диагноз", "Второй диагноз"]
    assert payload["diagnoses"] == ["Первый диагноз", "Второй диагноз"]
    assert card["unresolved_diagnosis_ids"] == ["999"]
    assert payload["unresolved_diagnosis_ids"] == ["999"]
    assert card["diagnos_type_text"].endswith("Второй диагноз (сопутствующий)")


def test_malformed_json_remains_visible_and_profile_parse_does_not_fail():
    from resources.pet_profile import _diagnosis_titles

    raw = '[{"id":124,"type":1}'
    titles, unresolved, references = _diagnosis_titles({"diagnos": raw}, {})
    assert titles == []
    assert unresolved == [raw]
    assert references == []


def test_json_references_ignore_invalid_entries_and_deduplicate_pairs():
    from resources.pet_profile import _diagnosis_titles

    card = {"diagnos": '[{"id":124,"type":0},{"id":124,"type":0},'
                       '{"id":124,"type":2},{"id":0,"type":1},'
                       '{"id":true,"type":1},{"id":125,"type":"2"}]'}
    titles, unresolved, references = _diagnosis_titles(card, {"124": "Первый"})
    assert titles == ["Первый"]
    assert unresolved == []
    assert references == [{"id": "124", "type": 0}, {"id": "124", "type": 2}]


def test_derived_diagnosis_fields_are_depersonalized():
    from depersonalization import REDACTED_NAME, sanitize_tool_result

    raw = "Владелец Иван Иванов сообщил о симптомах"
    payload = {
        "diagnoses": [raw],
        "unresolved_diagnosis_ids": ['[{"id":"' + raw + '"}'],
        "last_medical_cards": [{"diagnosis_titles": [raw]}],
    }
    cleaned = sanitize_tool_result(payload, tool_name="get_pet_profile")
    assert REDACTED_NAME in cleaned["diagnoses"][0]
    assert REDACTED_NAME in cleaned["unresolved_diagnosis_ids"][0]
    assert REDACTED_NAME in cleaned["last_medical_cards"][0]["diagnosis_titles"][0]
    assert raw not in str(cleaned)


def test_empty_json_array_does_not_promote_stale_card_text():
    from resources.pet_profile import _diagnosis_titles

    titles, unresolved, references = _diagnosis_titles(
        {"diagnos": "[]", "diagnos_text": "Старое название"}, {}
    )
    assert (titles, unresolved, references) == ([], [], [])


def test_json_text_preserves_independent_diagnoses_array_titles():
    from resources.pet_profile import _diagnosis_titles

    card = {"diagnos": '[{"id":124,"type":1}]',
            "diagnos_text": "Первый диагноз",
            "diagnoses": [{"id": 125}]}
    titles, unresolved, references = _diagnosis_titles(
        card, {"124": "Первый диагноз", "125": "Дополнительный диагноз"}
    )
    assert titles == ["Первый диагноз", "Дополнительный диагноз"]
    assert unresolved == []
    assert references == [{"id": "124", "type": 1}]


def test_legacy_scalar_keeps_dictionary_titles_when_text_differs():
    from resources.pet_profile import _diagnosis_titles

    card = {"diagnos": "124", "diagnos_text": "Текст не из справочника",
            "diagnoses": [{"id": 125}]}
    titles, unresolved, references = _diagnosis_titles(
        card, {"124": "Первый диагноз", "125": "Дополнительный диагноз"}
    )
    assert titles == ["Первый диагноз", "Дополнительный диагноз"]
    assert unresolved == []
    assert references == []


def test_independent_text_does_not_replace_catalog_diagnosis():
    from resources.pet_profile import _diagnosis_titles

    card = {"diagnos": '[{"id":124,"type":1}]',
            "diagnos_text": "Старый диагноз",
            "diagnos_type_text": "Старый диагноз (основной)"}
    titles, unresolved, references = _diagnosis_titles(
        card, {"124": "Текущий диагноз"}
    )
    assert titles == ["Текущий диагноз"]
    assert unresolved == []
    assert references == [{"id": "124", "type": 1}]


def test_text_without_typed_confirmation_does_not_invent_unresolved_title():
    from resources.pet_profile import _diagnosis_titles

    card = {"diagnos": '[{"id":999,"type":1}]',
            "diagnos_text": "Произвольная заметка", "diagnos_type_text": ""}
    titles, unresolved, references = _diagnosis_titles(card, {})
    assert titles == []
    assert unresolved == ["999"]
    assert references == [{"id": "999", "type": 1}]


@pytest.mark.parametrize("raw", ['[32]', '[{"id":32}]'])
def test_legacy_arrays_without_complete_references_remain_unresolved(raw):
    from resources.pet_profile import _diagnosis_titles

    titles, unresolved, references = _diagnosis_titles({"diagnos": raw}, {})
    assert titles == []
    assert unresolved == [raw]
    assert references == []
