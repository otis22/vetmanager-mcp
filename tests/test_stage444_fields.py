"""Projection contract for period invoice positions and medical-card lists."""

import pytest

from exceptions import ToolInputError
from list_projection import project_list_result, selected_fields
from server import mcp


@pytest.mark.asyncio
async def test_four_list_tools_publish_fields_only():
    catalog = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    for name in ("get_invoice_documents_by_period", "get_medical_cards",
                 "get_medical_cards_by_date", "get_medical_cards_by_client_id"):
        props = catalog[name].inputSchema["properties"]
        assert "fields" in props
        assert "compact" not in props and "include" not in props


@pytest.mark.parametrize("name,response,selection,expected_rows", [
    ("get_invoice_documents_by_period", {"data": {"invoiceDocument": [
        {"id": 9, "document_id": 3, "invoice_id": 3, "invoice_date": "2026-09-01", "price": "100", "good": {"id": 4}}],
        "totalCount": 1, "limited": False, "upstream_calls": 2, "next_offset": None}},
     ("id", "invoice_id"), [{"id": 9, "invoice_id": 3}]),
    ("get_medical_cards", {"success": True, "data": {"medicalCards": [
        {"id": 7, "pet_id": 2, "description": "private", "doctor": {"id": 1}}], "totalCount": 1}},
     ("id", "pet_id"), [{"id": 7, "pet_id": 2}]),
    ("get_medical_cards_by_date", {"success": True, "medical_cards": [
        {"id": 7, "pet_id": 2, "description": "private"}], "date_from": "2026-09-01",
        "date_to": "2026-09-01", "total": 1, "total_known": True,
        "medical_cards_count": 1, "truncated": False, "clinic_filter_applied": False,
        "clinic_id": None, "limit": 20, "offset": 0, "owner_context_available": False},
     ("id", "pet_id"), [{"id": 7, "pet_id": 2}]),
    ("get_medical_cards_by_client_id", {"success": True, "medical_cards": [
        {"id": 7, "pet_id": 2, "_pet_alias": "Pet"}], "client_id": 1,
        "pets_count": 1, "pets_total": 3, "pets_truncated": True,
        "medical_cards_count": 1, "medical_cards_total": 1,
        "medical_cards_has_more": False},
     ("id", "_pet_alias"), [{"id": 7, "_pet_alias": "Pet"}]),
])
def test_projected_rows_preserve_envelope_and_counts(name, response, selection, expected_rows):
    projected = project_list_result(response, name, selection)
    key = "invoiceDocument" if name == "get_invoice_documents_by_period" else (
        "medicalCards" if name == "get_medical_cards" else "medical_cards")
    rows = projected["data"][key] if "data" in projected else projected[key]
    assert rows == expected_rows
    assert {k: v for k, v in projected.items() if k != "data" and k != "medical_cards"} == {
        k: v for k, v in response.items() if k != "data" and k != "medical_cards"}
    if "data" in response:
        assert {k: v for k, v in projected["data"].items() if k != key} == {
            k: v for k, v in response["data"].items() if k != key}


def test_limited_advice_and_error_are_preserved():
    response = {"data": {"invoiceDocument": [], "totalCount": None,
                          "limited": True, "limited_reason": "upstream_call_budget",
                          "upstream_calls": 20, "next_offset": None,
                          "advice": "Narrow date_from/date_to"}}
    assert project_list_result(response, "get_invoice_documents_by_period", ("id",)) == response
    error = {"success": False, "error": "upstream failed"}
    assert project_list_result(error, "get_medical_cards", ("id",)) == error


def test_unknown_fields_are_rejected_before_io():
    for name in ("get_invoice_documents_by_period", "get_medical_cards",
                 "get_medical_cards_by_date", "get_medical_cards_by_client_id"):
        with pytest.raises(ToolInputError):
            selected_fields(name, ["good"], False)
        with pytest.raises(ToolInputError):
            selected_fields(name, [], False)

@pytest.mark.asyncio
async def test_mcp_fields_project_after_identifier_normalization(monkeypatch):
    from tests.runtime_factories import patch_runtime_credentials
    from vetmanager_client import VetmanagerClient

    async def get(_self, path, **_kwargs):
        assert path == "/rest/api/MedicalCards"
        return {"success": True, "data": {"medicalCards": [
            {"id": 7, "patient_id": 2, "description": '<a href="https://files.example.test/x">file</a>',
             "doctor": {"id": 1}}], "totalCount": 1}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = patch_runtime_credentials("testclinic", "mock-key")
    with headers, runtime:
        full = await mcp.call_tool("get_medical_cards", {"pet_id": 2})
        result = await mcp.call_tool("get_medical_cards", {
            "pet_id": 2, "fields": ["id", "pet_id"]})
    assert result.structured_content["data"]["medicalCards"] == [{"id": 7, "pet_id": 2}]
    assert "<a href=" in full.structured_content["data"]["medicalCards"][0]["description"]


@pytest.mark.asyncio
async def test_period_fields_preserve_invoice_parent_and_metadata(monkeypatch):
    from tests.runtime_factories import patch_runtime_credentials
    from vetmanager_client import VetmanagerClient

    async def get(_self, path, **_kwargs):
        if path == "/rest/api/invoice":
            return {"success": True, "data": {"invoice": [
                {"id": 3, "invoice_date": "2026-09-01 10:00:00"}], "totalCount": 1}}
        if path == "/rest/api/invoiceDocument":
            return {"success": True, "data": {"invoiceDocument": [
                {"id": 9, "document_id": 3, "price": "100", "good": {"id": 1}}],
                "totalCount": 1}}
        raise AssertionError(path)

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = patch_runtime_credentials("testclinic", "mock-key")
    with headers, runtime:
        result = await mcp.call_tool("get_invoice_documents_by_period", {
            "date_from": "2026-09-01", "date_to": "2026-09-01",
            "fields": ["id", "document_id", "invoice_id", "invoice_date"],
        })
    assert result.structured_content["data"]["invoiceDocument"] == [
        {"id": 9, "document_id": 3, "invoice_id": 3,
         "invoice_date": "2026-09-01 10:00:00"}]
    assert result.structured_content["data"]["totalCount"] == 1

@pytest.mark.asyncio
async def test_projected_clinical_text_is_cleaned_before_selection(monkeypatch):
    from tests.runtime_factories import patch_runtime_credentials
    from vetmanager_client import VetmanagerClient

    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [
            {"id": 7, "patient_id": 2,
             "description": "Call +7 999 123 45 67"}], "totalCount": 1}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = patch_runtime_credentials(
        "testclinic", "mock-key", is_depersonalized=True)
    with headers, runtime:
        result = await mcp.call_tool("get_medical_cards", {
            "pet_id": 2, "fields": ["id", "pet_id", "description"]})
    row = result.structured_content["data"]["medicalCards"][0]
    assert row["pet_id"] == 2
    assert "+7 999 123 45 67" not in row["description"]
