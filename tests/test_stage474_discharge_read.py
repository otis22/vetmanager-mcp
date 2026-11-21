"""Stage 474: one read scenario, explicit source gaps, no implicit write."""
from datetime import date
from types import SimpleNamespace

import pytest

from tool_access_registry import TOOL_REQUIRED_SCOPES, PRESET_DOCTOR, TOKEN_PRESET_SCOPES
from token_scopes import SCOPE_ADMISSIONS_READ, SCOPE_MEDICAL_CARDS_READ, SCOPE_PETS_READ
from tools.discharge_history import _add_vaccinations, _project, _select_period, fetch_history
from tools.discharge_history import _scan
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from depersonalization import sanitize_tool_result


START, END = date(2026, 1, 10), date(2026, 1, 20)


def test_period_includes_linked_card_and_overlapping_hospital():
    admission = {"id": 8, "patient_id": 7, "admission_date": "2026-01-15 10:00:00"}
    cards = [
        {"id": 1, "patient_id": 7, "admission_id": 8, "date_create": "2026-02-01 10:00:00"},
        {"id": 2, "patient_id": 7, "date_create": "2026-01-20 23:59:59"},
    ]
    selected, gaps = _select_period("medical_cards", cards, START, END, {8})
    assert {row["id"] for row in selected} == {1, 2}
    assert gaps == []
    stays, gaps = _select_period("hospitalizations", [
        {"id": 3, "pet_id": 7, "start_date": "2026-01-01", "end_date": "2026-01-12"},
        {"id": 4, "pet_id": 7, "start_date": "2026-01-01", "end_date": "0000-00-00 00:00:00"},
    ], START, END, set())
    assert {row["id"] for row in stays} == {3, 4}
    assert any("unknown" in gap for gap in gaps)


def test_linked_card_with_string_ids_is_included():
    cards = [{"id": "1", "patient_id": "7", "admission_id": "8",
              "date_create": "2026-02-01", "description": "linked exam"}]
    selected, gaps = _select_period("medical_cards", cards, START, END, {8})
    assert selected[0]["id"] == "1"
    assert gaps == []


def test_invoice_fallback_date_outside_period_has_no_gap():
    invoice = {"id": 91, "pet_id": 7, "invoice_date": None,
               "create_date": "2025-12-01"}
    selected, gaps = _select_period("invoices", [invoice], START, END, set())
    assert selected == []
    assert gaps == []


def test_medical_card_keeps_supported_clinical_fields():
    card = {"id": 1, "patient_id": 7, "recommendation": "rest",
            "healing_process": "therapy", "diagnoses": [{"id": 3, "title": "Condition"}]}
    projected = _project("medical_cards", card)
    assert projected["recommendation"] == "rest"
    assert projected["healing_process"] == "therapy"
    assert projected["diagnoses"] == [{"id": 3, "title": "Condition"}]


def test_embedded_invoice_lines_are_never_returned_unverified():
    invoice = {"id": None, "pet_id": 7, "invoice_date": "2026-01-15",
               "invoice_documents": [{"document_id": 99, "good": {"title": "Other patient"}}]}
    assert "invoice_documents" not in _project("invoices", invoice)


def test_scope_is_clinical_and_finance_remains_optional():
    assert TOOL_REQUIRED_SCOPES["get_pet_discharge_history"] == (
        SCOPE_ADMISSIONS_READ, SCOPE_MEDICAL_CARDS_READ, SCOPE_PETS_READ,
    )
    assert set(TOOL_REQUIRED_SCOPES["get_pet_discharge_history"]).issubset(
        TOKEN_PRESET_SCOPES[PRESET_DOCTOR]
    )


@pytest.mark.asyncio
async def test_admission_list_variant_preserves_rows_with_unknown_total():
    async def fake_get(path, params=None):
        return {"success": True, "data": [{"id": 1, "patient_id": 7}]}

    rows, gaps = await _scan(SimpleNamespace(get=fake_get), "/rest/api/admission", "admission", [], 100)
    assert rows == [{"id": 1, "patient_id": 7}]
    assert "admission:unknown_totalCount" in gaps


@pytest.mark.asyncio
async def test_invoice_line_request_budget_refuses_an_extra_upstream_call():
    async def fail_get(path, params=None):
        raise AssertionError("budget exhausted: no request allowed")

    rows, gaps = await _scan(SimpleNamespace(get=fail_get), "/rest/api/invoiceDocument",
                             "invoiceDocument", [], 100, request_budget=[100])
    assert rows == []
    assert "invoiceDocument:request_budget_exhausted" in gaps


@pytest.mark.asyncio
async def test_history_collects_all_pages_and_never_writes(monkeypatch):
    calls = []

    async def fake_get(self, path, params=None):
        calls.append((path, params))
        if path == "/rest/api/pet/7":
            return {"success": True, "data": {"pet": {"id": 7, "alias": "Patient"}}}
        if path == "/rest/api/MedicalCards/Vaccinations":
            return {"success": True, "data": {"medicalcards": [], "totalCount": 0}}
        data = {
            "/rest/api/admission": ("admission", [{"id": "8", "patient_id": 7, "admission_date": "2026-01-15"}]),
            "/rest/api/MedicalCards": ("medicalCards", [{"id": 1, "patient_id": 7, "admission_id": "8", "date_create": "2026-02-01", "description": "Exam"}]),
            "/rest/api/hospital": ("hospital", []),
            "/rest/api/invoice": ("invoice", []),
        }
        key, rows = data[path]
        offset = params.get("offset", 0)
        return {"success": True, "data": {key: rows[offset:offset + 1], "totalCount": len(rows)}}

    monkeypatch.setattr("tools.discharge_history.VetmanagerClient", lambda: SimpleNamespace(
        get=lambda path, params=None: fake_get(None, path, params)))
    result = await fetch_history(7, "2026-01-10", "2026-01-20", finance_allowed=False, page_size=1)
    assert result["medical_cards"]["records"][0]["id"] == 1
    assert result["medical_cards"]["complete"] is True
    assert result["invoices"]["complete"] is False
    assert result["invoices"]["evidence_kind"] == "accounting_records_not_proof_of_treatment"
    assert any("finance.read" in gap for gap in result["gaps"])
    assert all(path.startswith("/rest/api/") for path, _ in calls)
    assert not any(path.startswith("/rest/api/invoice") for path, _ in calls)


@pytest.mark.asyncio
async def test_financial_lines_and_vaccination_truncation_are_explicit(monkeypatch):
    async def fake_get(path, params=None):
        if path == "/rest/api/pet/7":
            return {"data": {"pet": {"id": 7}}}
        if path == "/rest/api/MedicalCards/Vaccinations":
            return {"data": {"medicalcards": [{"id": 4, "date": "2026-01-12"}], "totalCount": 2}}
        rows_by_path = {
            "/rest/api/admission": ("admission", []),
            "/rest/api/MedicalCards": ("medicalCards", []),
            "/rest/api/hospital": ("hospital", []),
            "/rest/api/invoice": ("invoice", [{"id": "9", "pet_id": 7, "invoice_date": "2026-01-15", "amount": 100}]),
            "/rest/api/invoiceDocument": ("invoiceDocument", [{"id": 10, "document_id": 9, "quantity": 1, "good": {"title": "Service", "price": 100}}]),
        }
        key, rows = rows_by_path[path]
        return {"data": {key: rows, "totalCount": len(rows)}}

    monkeypatch.setattr("tools.discharge_history.VetmanagerClient", lambda: SimpleNamespace(get=fake_get))
    result = await fetch_history(7, "2026-01-10", "2026-01-20", finance_allowed=True)
    assert result["invoices"]["records"][0]["invoice_documents"] == [
        {"id": 10, "document_id": 9, "quantity": 1, "good": {"title": "Service"}}
    ]
    assert result["vaccinations"]["complete"] is False
    assert result["complete"] is False
    assert result["invoices"]["evidence_kind"] == "accounting_records_not_proof_of_treatment"


@pytest.mark.asyncio
async def test_ignored_upstream_patient_filter_cannot_expose_other_patient(monkeypatch):
    async def fake_get(path, params=None):
        if path == "/rest/api/pet/7":
            return {"data": {"pet": {"id": 7}}}
        if path == "/rest/api/MedicalCards/Vaccinations":
            return {"data": {"medicalcards": [], "totalCount": 0}}
        key = {"/rest/api/admission": "admission", "/rest/api/MedicalCards": "medicalCards",
               "/rest/api/hospital": "hospital", "/rest/api/invoice": "invoice"}[path]
        rows = [{"id": 42, "patient_id": 99, "date_create": "2026-01-15",
                 "description": "other patient's note"}] if key == "medicalCards" else []
        return {"data": {key: rows, "totalCount": len(rows)}}

    monkeypatch.setattr("tools.discharge_history.VetmanagerClient", lambda: SimpleNamespace(get=fake_get))
    result = await fetch_history(7, "2026-01-10", "2026-01-20", finance_allowed=False)
    assert result["medical_cards"]["records"] == []
    assert result["medical_cards"]["complete"] is False


def test_unread_attachment_and_unresolved_diagnosis_are_gaps():
    card = {"id": 5, "patient_id": 7, "date_create": "2026-01-15",
            "description": '<a href="/attachment/123">file</a>',
            "diagnos": '[{"id":3,"type":1}]'}
    records, gaps = _select_period("medical_cards", [card], START, END, set())
    assert records[0]["id"] == 5
    assert any("attachment" in gap for gap in gaps)
    assert any("diagnosis" in gap for gap in gaps)


@pytest.mark.asyncio
async def test_vaccination_without_patient_link_is_not_returned(monkeypatch):
    async def fake_get(path, params=None):
        if path == "/rest/api/pet/7":
            return {"data": {"pet": {"id": 7}}}
        if path == "/rest/api/MedicalCards/Vaccinations":
            return {"data": {"medicalcards": [{"id": 4, "medcard_id": 99, "pet_id": 7,
                                                 "date": "2026-01-12"}],
                             "totalCount": 1}}
        key = {"/rest/api/admission": "admission", "/rest/api/MedicalCards": "medicalCards",
               "/rest/api/hospital": "hospital"}[path]
        return {"data": {key: [], "totalCount": 0}}

    monkeypatch.setattr("tools.discharge_history.VetmanagerClient", lambda: SimpleNamespace(get=fake_get))
    result = await fetch_history(7, "2026-01-10", "2026-01-20", finance_allowed=False)
    assert result["vaccinations"]["records"] == []
    assert result["vaccinations"]["complete"] is False


@pytest.mark.asyncio
async def test_depersonalized_boundary_scrubs_nested_patient(monkeypatch):
    async def fake_fetch(*args, **kwargs):
        return {"pet": {"records": [{"id": 7, "alias": "Марс"}]},
                "medical_cards": {"records": [{"description": "ivan@example.com",
                                               "healing_process": "petr@example.com"}]}}

    monkeypatch.setattr("tools.discharge_history.fetch_history", fake_fetch)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", is_depersonalized=True)
    with headers, runtime:
        answer = (await mcp.call_tool("get_pet_discharge_history", {
            "pet_id": 7, "date_from": "2026-01-10", "date_to": "2026-01-20"})).structured_content
    assert "ivan@example.com" not in answer["medical_cards"]["records"][0]["description"]
    assert "petr@example.com" not in answer["medical_cards"]["records"][0]["healing_process"]


def test_healing_process_clean_text_is_preserved():
    record = {"medical_cards": {"records": [{"healing_process": "Осмотр и лечение"}]}}
    assert sanitize_tool_result(record, tool_name="get_pet_discharge_history") == record


@pytest.mark.asyncio
async def test_scan_marks_total_below_fetched_rows_incomplete():
    async def fake_get(*args, **kwargs):
        return {"success": True, "data": {"admission": [{"id": 1}, {"id": 2}], "totalCount": 1}}

    rows, gaps = await _scan(SimpleNamespace(get=fake_get), "/rest/api/admission", "admission", [], 100)
    assert len(rows) == 2
    assert "admission:totalCount_below_fetched" in gaps


@pytest.mark.asyncio
async def test_scan_caps_rows_even_if_upstream_ignores_page_limit():
    oversized_page = [{"id": identifier} for identifier in range(1, 10_002)]

    async def fake_get(*args, **kwargs):
        return {"success": True, "data": {"admission": oversized_page, "totalCount": len(oversized_page)}}

    rows, gaps = await _scan(SimpleNamespace(get=fake_get), "/rest/api/admission", "admission", [], 100)
    assert len(rows) == 10_000
    assert "admission:row_cap_reached" in gaps


def test_diagnosis_note_does_not_resolve_catalog_reference():
    row = {"id": 5, "patient_id": 7, "date_create": "2026-01-15",
           "diagnos": '[{"id":3,"type":1}]', "diagnos_text": "Follow-up required"}
    _, gaps = _select_period("medical_cards", [row], START, END, set())
    assert "medical_cards:5:diagnosis_title_unresolved" in gaps


def test_matching_diagnosis_title_resolves_catalog_reference():
    row = {"id": 5, "patient_id": 7, "date_create": "2026-01-15",
           "diagnos": '[{"id":3,"type":1}]',
           "diagnoses": [{"id": 3, "title": "Condition"}]}
    _, gaps = _select_period("medical_cards", [row], START, END, set())
    assert "medical_cards:5:diagnosis_title_unresolved" not in gaps


@pytest.mark.asyncio
async def test_vaccination_rows_are_capped_when_upstream_ignores_limit():
    rows = [{"id": number, "medcard_id": 5, "date": "2026-01-15"}
            for number in range(1, 10_002)]

    async def fake_get(*args, **kwargs):
        return {"success": True, "data": {"medicalcards": rows, "totalCount": len(rows)}}

    result = {}
    await _add_vaccinations(SimpleNamespace(get=fake_get), result, 7, START, END, {"5"})
    assert result["vaccinations"]["count"] == 100
    assert "vaccinations:upstream_limit_exceeded" in result["vaccinations"]["gaps"]


@pytest.mark.asyncio
async def test_vaccination_total_below_fetched_rows_is_incomplete():
    rows = [{"id": 1, "medcard_id": 5, "date": "2026-01-15"},
            {"id": 2, "medcard_id": 5, "date": "2026-01-15"}]

    async def fake_get(*args, **kwargs):
        return {"success": True, "data": {"medicalcards": rows, "totalCount": 1}}

    result = {}
    await _add_vaccinations(SimpleNamespace(get=fake_get), result, 7, START, END, {"5"})
    assert result["vaccinations"]["count"] == 2
    assert "vaccinations:unpageable_or_unknown_total" in result["vaccinations"]["gaps"]


@pytest.mark.parametrize("field", ("diagnos", "diagnos_text", "diagnos_type_text"))
def test_depersonalized_diagnosis_fields_scrub_personal_text(field):
    record = {"medical_cards": {"records": [{field: "owner@example.com"}]}}
    cleaned = sanitize_tool_result(record, tool_name="get_pet_discharge_history")
    assert "owner@example.com" not in cleaned["medical_cards"]["records"][0][field]


def test_vaccine_name_and_nested_good_description_scrub_personal_text():
    vaccination = _project("vaccinations", {"id": 1, "name": "owner@example.com"})
    record = {"vaccinations": {"records": [vaccination]},
              "invoices": {"records": [{"invoice_documents": [
                  {"good": {"description": "owner@example.com"}}]}]}}
    cleaned = sanitize_tool_result(record, tool_name="get_pet_discharge_history")
    assert "owner@example.com" not in cleaned["vaccinations"]["records"][0]["vaccine_name"]
    assert "owner@example.com" not in cleaned["invoices"]["records"][0]["invoice_documents"][0]["good"]["description"]
    assert sanitize_tool_result({"vaccinations": {"records": [{"vaccine_name": "Rabies"}]}})["vaccinations"]["records"][0]["vaccine_name"] == "Rabies"
