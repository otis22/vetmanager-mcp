"""Stage 422: report reject and partial profile errors cross the MCP privacy boundary."""

import asyncio
import httpx
import pytest
from types import SimpleNamespace
import respx

from depersonalization import REDACTED_EMAIL, REDACTED_NAME, sanitize_tool_result
from server import mcp
from resources._aggregation import gather_sections
from runtime_auth import use_runtime_credentials
from tests.runtime_factories import patch_runtime_credentials


BASE = "https://testclinic.vetmanager.cloud"


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden", [True, False])
@respx.mock
async def test_reject_preview_arbitrary_columns_obey_token_privacy(hidden):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    preview = {"col_7": "Иванов Пётр Сергеевич", "random_value": "owner@example.com",
               "good": "owner@example.com", "clinic": "Иванов Пётр Сергеевич",
               "owner@example.com": "safe",
               "service": "Вакцинация комплексная"}
    respx.post(f"{BASE}/rest/api/report-ai-job/22/reject").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": {
            "id": 22, "status": "queued", "recognized": {"preview_example_row": preview}}}})
    )
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", is_depersonalized=hidden)
    with headers, runtime:
        result = await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 22})
    row = result.structured_content["data"]["job"]["recognized"]["preview_example_row"]
    assert row["col_7"] == (REDACTED_NAME if hidden else preview["col_7"])
    assert row["random_value"] == (REDACTED_EMAIL if hidden else preview["random_value"])
    assert row["good"] == (REDACTED_EMAIL if hidden else preview["good"])
    assert row["clinic"] == (REDACTED_NAME if hidden else preview["clinic"])
    assert row["service"] == preview["service"]
    assert (REDACTED_EMAIL if hidden else "owner@example.com") in row
    if hidden:
        assert "owner@example.com" not in row


def test_report_column_key_collision_fails_closed():
    with pytest.raises(ValueError, match="column"):
        sanitize_tool_result({"preview_example_row": {
            "first@example.com": "one", "second@example.com": "two",
        }}, report_mode=True)


def test_report_column_name_with_street_marker_does_not_hide_a_full_name():
    row = sanitize_tool_result({"preview_example_row": {
        "Smith John Doe улица": "safe",
    }}, report_mode=True)["preview_example_row"]
    assert "Smith John Doe улица" not in row
    assert any("[redacted-name]" in key for key in row)


@pytest.mark.parametrize("raw_name", ["Иванов И. И. улица", "Smith John Doe улица"])
@pytest.mark.parametrize("as_dict", [True, False])
def test_report_column_initials_and_metadata_match_cleaned_row_keys(raw_name, as_dict):
    column = {"name": raw_name, "type": "text"} if as_dict else raw_name
    clean = sanitize_tool_result({"data": {
        "columns": [column],
        "rows": [{raw_name: "safe"}],
    }}, report_mode=True)["data"]
    names = [clean["columns"][0]["name"] if as_dict else clean["columns"][0]]
    assert all("Иванов" not in name and "Smith John Doe" not in name for name in names)
    assert set(names) == set(clean["rows"][0])


def test_report_column_metadata_collision_fails_closed():
    with pytest.raises(ValueError, match="column"):
        sanitize_tool_result({"columns": ["first@example.com", "second@example.com"]}, report_mode=True)


def test_malformed_nested_section_error_fails_closed():
    from tools import _safe_profile_section_errors

    with pytest.raises(ValueError, match="section error"):
        _safe_profile_section_errors({"section_errors": {
            "invoice_documents": {"42": "owner@example.com"},
        }})


def test_malformed_invoice_entry_with_section_error_fails_closed():
    from tools import _safe_profile_section_errors

    with pytest.raises(ValueError, match="invoice"):
        _safe_profile_section_errors({"section_errors": {
            "invoices": {"error_type": "unexpected", "retryable": False,
                         "message": "owner@example.com"},
        }, "last_invoices": ["owner@example.com"]})


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden", [True, False])
@pytest.mark.parametrize("tool_name,resource_name,identifier", [
    ("get_client_profile", "client_profile", "client_id"),
    ("get_pet_profile", "pet_profile", "pet_id"),
])
async def test_partial_profile_error_message_obeys_token_privacy(
    monkeypatch, hidden, tool_name, resource_name, identifier
):
    async def partial(*, tool_name, context, sections):
        for _, coro, _ in sections:
            coro.close()
        payloads = [fallback for _, _, fallback in sections]
        return payloads, {"invoices": {"error_type": "vetmanager_error", "retryable": True,
                                      "message": "VetmanagerError: Иванов Пётр Сергеевич owner@example.com; timeout",
                                      "detail": "owner@example.com"}}

    # The resource's real aggregation path returns the structured error to the
    # registered MCP tool; no upstream credentials are needed for this boundary test.
    monkeypatch.setattr(f"resources.{resource_name}.gather_sections", partial)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", is_depersonalized=hidden)
    with headers, runtime:
        result = await mcp.call_tool(tool_name, {identifier: 7})
    body = result.structured_content
    assert body["partial"] is True
    error = body["section_errors"]["invoices"]
    assert error["error_type"] == "vetmanager_error"
    assert error["retryable"] is True
    if hidden:
        assert "detail" not in error
        assert "Иванов" not in error["message"]
        assert "owner@example.com" not in error["message"]
        assert error["message"] == "Section request failed; see error_type and retryable."
    else:
        assert error["detail"] == "owner@example.com"
        assert "Иванов Пётр Сергеевич owner@example.com; timeout" in error["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("hidden", [True, False])
async def test_pet_invoice_document_error_duplicate_is_private(monkeypatch, hidden):
    async def fetch(_pet_id):
        error = {"error_type": "invoice_documents_error", "retryable": True,
                 "message": "VetmanagerError: Иванов Пётр Сергеевич owner@example.com",
                 "detail": "owner@example.com"}
        return {"pet": {"id": 7}, "last_invoices": [{"id": 42, "invoice_documents_error": error}],
                "partial": True, "section_errors": {"invoice_documents": {"42": error}}}

    monkeypatch.setattr("tools.pet._fetch_pet_profile", fetch)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", is_depersonalized=hidden)
    with headers, runtime:
        result = await mcp.call_tool("get_pet_profile", {"pet_id": 7})
    body = result.structured_content
    nested = body["section_errors"]["invoice_documents"]["42"]
    duplicate = body["last_invoices"][0]["invoice_documents_error"]
    for error in (nested, duplicate):
        assert error["error_type"] == "invoice_documents_error"
        assert error["retryable"] is True
        assert ("detail" not in error) if hidden else (error["detail"] == "owner@example.com")
        assert error["message"] == ("Section request failed; see error_type and retryable."
                                    if hidden else "VetmanagerError: Иванов Пётр Сергеевич owner@example.com")


@pytest.mark.asyncio
async def test_aggregator_log_omits_exception_text_for_both_token_modes(caplog):
    async def fail():
        await asyncio.sleep(0)
        raise ValueError("Иванов Пётр Сергеевич owner@example.com")

    for hidden in (True, False):
        caplog.clear()
        with use_runtime_credentials(SimpleNamespace(is_depersonalized=hidden)):
            _, errors = await gather_sections(
                tool_name="get_client_profile", context={"client_id": 7},
                sections=[("invoices", fail(), {"data": {"invoice": []}})],
            )
        assert "Иванов Пётр Сергеевич" in errors["invoices"]["message"]
        assert "Иванов Пётр Сергеевич" not in caplog.text
        assert "owner@example.com" not in caplog.text
        assert caplog.records[-1].section_errors["invoices"] == {
            "error_type": "unexpected", "retryable": False,
        }
