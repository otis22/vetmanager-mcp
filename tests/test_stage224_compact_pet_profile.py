"""Этап 224 — анкета питомца краткая, подробности отдельным запросом.

Замер на тестовом стенде: анкета питомца с **четырьмя** медкартами и
**четырьмя** счетами весила около 14 КБ. Проблема не в длинной истории — ответ
раздут на самом маленьком возможном пациенте, потому что одни и те же записи
повторяются:

    владелец  — шесть раз (owner, pet.owner и копия внутри каждого счёта)
    питомец   — пять раз (верхний уровень и копия внутри каждого счёта)
    счёт      — ещё раз внутри каждой своей позиции

Тесты держат два свойства: повторов нет, и агенту сказано, чего в ответе нет и
как это получить. Второе не украшение: молчаливое отсутствие данных агент читает
как «данных нет» — тот же класс, что этапы 296 и 301.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"

_OWNER = {
    "id": 12, "first_name": "Сергей", "last_name": "Морозова",
    "cell_phone": "+79992000003", "balance": "0.0000000000", "status": "ACTIVE",
}
_PET = {
    "id": 10, "owner_id": 12, "alias": "Марс", "sex": "male",
    "birthday": "2022-07-19", "status": "alive", "weight": "4.07",
    "owner": dict(_OWNER),
}
_INVOICE = {
    "id": 2428, "doctor_id": 10, "client_id": 12, "pet_id": 10,
    "description": "Приём", "amount": "3600.0000000000", "status": "exec",
    "invoice_date": "2026-09-04 13:00:00", "paid_amount": "0.0000000000",
    "client": dict(_OWNER),
    "pet": dict(_PET),
}
_INVOICE_DOC = {
    "id": 3750, "document_id": 2428, "good_id": 34,
    "quantity": "1.0000000000", "price": "2100.0000000000",
    "document": dict(_INVOICE),
    "good": {"id": 34, "title": "Первичный приём врача", "group_id": 72,
             "prime_cost": "0.0000000000", "is_active": 1},
    "goodSaleParam": {"id": 38, "good_id": 34, "price": "2100.0000000000",
                      "price_formation": "fixed", "clinic_id": 1},
}
_CARD = {
    "id": 7022, "patient_id": 10, "date_create": "2026-09-04 13:00:00",
    "diagnos": "0", "description": "Кашель без повышения температуры",
    "recomendation": "Связаться с клиникой", "doctor_id": 10,
    "weight": "4.07", "temperature": "38.7", "status": "active",
    "patient": dict(_PET),
}


def _mocks() -> None:
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/pet/10").mock(
        return_value=httpx.Response(200, json={"data": {"pet": dict(_PET)}})
    )
    respx.get(f"{BASE}/rest/api/client/12").mock(
        return_value=httpx.Response(200, json={"data": {"client": dict(_OWNER)}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200, json={"data": {"medicalCards": [dict(_CARD)], "totalCount": 37}}
        )
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": {"diagnoses": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}})
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200, json={"data": {"invoice": [dict(_INVOICE)], "totalCount": 9}}
        )
    )
    respx.get(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(
            200, json={"data": {"invoiceDocument": [dict(_INVOICE_DOC)], "totalCount": 1}}
        )
    )


async def _profile() -> dict:
    _mocks()
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token"
    )
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pet_profile", {"pet_id": 10})
    return result.structured_content if hasattr(result, "structured_content") else result


def _occurrences(payload: dict, needle: str) -> int:
    return json.dumps(payload, ensure_ascii=False).count(needle)


@pytest.mark.asyncio
@respx.mock
async def test_owner_record_is_not_repeated() -> None:
    """Владелец приезжал шесть раз: верхний уровень, `pet.owner` и по копии
    внутри каждого счёта."""
    profile = await _profile()

    assert profile["owner"]["id"] == 12, "раздел владельца должен остаться"
    assert "owner" not in profile["pet"], "копия владельца внутри питомца"
    for invoice in profile["last_invoices"]:
        assert "client" not in invoice, "копия владельца внутри счёта"
    assert _occurrences(profile, '"cell_phone"') == 1


@pytest.mark.asyncio
@respx.mock
async def test_pet_record_is_not_repeated_inside_invoices() -> None:
    profile = await _profile()

    assert profile["pet"]["id"] == 10
    for invoice in profile["last_invoices"]:
        assert "pet" not in invoice, "копия питомца внутри счёта"


@pytest.mark.asyncio
@respx.mock
async def test_invoice_is_not_repeated_inside_its_own_line_items() -> None:
    """Счёт с двумя позициями содержал сам себя трижды."""
    profile = await _profile()

    for invoice in profile["last_invoices"]:
        for line in invoice.get("invoice_documents", []):
            assert "document" not in line, "счёт повторён внутри своей позиции"


@pytest.mark.asyncio
@respx.mock
async def test_line_items_keep_what_they_are_read_for() -> None:
    """Сжатие не должно съесть смысл позиции: название, цена, количество."""
    profile = await _profile()
    line = profile["last_invoices"][0]["invoice_documents"][0]

    assert line["good_title"] == "Первичный приём врача"
    assert line["price"] == "2100.0000000000"
    assert line["quantity"] == "1.0000000000"
    assert "goodSaleParam" not in line


@pytest.mark.asyncio
@respx.mock
async def test_medical_cards_are_short_but_clinical() -> None:
    profile = await _profile()
    card = profile["last_medical_cards"][0]

    for field in ("id", "date_create", "doctor_id", "description", "weight", "temperature"):
        assert field in card, f"из краткой карты пропало клинически важное поле {field}"
    assert "patient" not in card


@pytest.mark.asyncio
@respx.mock
async def test_counts_show_that_history_is_longer_than_shown() -> None:
    """Агент должен видеть, что показано не всё, — иначе решит, что всё."""
    profile = await _profile()

    assert profile["medical_cards_total"] == 37
    assert profile["medical_cards_returned"] == 1
    assert profile["medical_cards_truncated"] is True


@pytest.mark.asyncio
@respx.mock
async def test_the_answer_says_how_to_get_the_rest() -> None:
    """Молчаливое отсутствие данных агент читает как «данных нет»."""
    profile = await _profile()

    more = profile.get("more_details")
    assert more, "в ответе не сказано, чего нет и как это получить"
    rendered = json.dumps(more, ensure_ascii=False)
    assert "get_medical_cards_by_client_id" in rendered or "get_medical_cards" in rendered
    assert "get_invoice_documents" in rendered
    assert "10" in rendered, "в подсказке должен быть идентификатор питомца"
