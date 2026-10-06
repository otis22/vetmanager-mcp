"""Report AI keeps explicit quantities while retaining the phone boundary."""

import httpx
import pytest
import respx

from depersonalization import REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result
from report_export import build_export_csv
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from token_scopes import SCOPE_ANALYTICS_READ


@pytest.mark.asyncio
@respx.mock
async def test_job_data_keeps_quantity_and_hides_marked_contact() -> None:
    billing_mock()
    rows = [{"Количество": "1234567890", "Примечание": "тел. 912 345 67 89"}]
    respx.get(f"{BASE}/rest/api/report-ai-job/368/data").mock(return_value=httpx.Response(
        200, json={"success": True, "data": {"columns": list(rows[0]), "rows": rows,
                                         "total": 1, "limited": False}},
    ))
    headers, runtime = bearer_runtime_patch(
        scopes=(SCOPE_ANALYTICS_READ,), is_depersonalized=True,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": 368})
    row = result.structured_content["data"]["rows"][0]
    assert row == {"Количество": "1234567890", "Примечание": f"тел. {REDACTED_PHONE}"}


@pytest.mark.parametrize("column", ["Количество", " количество ", "COUNT", "qty"])
@pytest.mark.parametrize("value", ["1234567890", "12345678901"])
def test_exact_quantitative_column_keeps_numeric_cell_in_json_and_csv(column: str, value: str) -> None:
    payload = {"data": {"rows": [{column: value}]}}
    assert sanitize_tool_result(payload, report_mode=True, tool_name="get_report_ai_job_data")["data"]["rows"][0][column] == value
    assert sanitize_report_cell(column, value) == value
    csv_text, _, _ = build_export_csv(f"{column}\n{value}\n".encode(), delimiter=",", depersonalize=True)
    assert value in csv_text


@pytest.mark.parametrize("column", ["Телефон", "Значение", "count?", "c o u n t", "Количество телефонов"])
@pytest.mark.parametrize("value", ["1234567890", "12345678901"])
def test_unknown_or_contact_column_keeps_existing_phone_mask(column: str, value: str) -> None:
    payload = {"data": {"rows": [{column: value}]}}
    assert sanitize_tool_result(payload, report_mode=True, tool_name="get_report_ai_job_data")["data"]["rows"][0][column] == REDACTED_PHONE
    assert sanitize_report_cell(column, value) == REDACTED_PHONE


@pytest.mark.parametrize("value", [
    "тел. 912 345 67 89", "звонить 912.345.67.89",
    "тел. 912 345 67 89, 913 456 78 90", "+7 999 123-45-67",
])
def test_marked_contacts_and_lists_in_quantity_column_remain_masked(value: str) -> None:
    cleaned = sanitize_report_cell("Количество", value)
    assert "912" not in cleaned and "913" not in cleaned and "999" not in cleaned
    assert REDACTED_PHONE in cleaned
    csv_text, _, _ = build_export_csv(f'Количество\n"{value}"\n'.encode(), delimiter=",", depersonalize=True)
    assert REDACTED_PHONE in csv_text


def test_non_numeric_value_in_quantity_column_uses_existing_report_cleaning() -> None:
    assert sanitize_report_cell("Количество", "1234567890 ед") == f"{REDACTED_PHONE} ед"


def test_quantity_exception_does_not_apply_outside_job_data_rows() -> None:
    value = "1234567890"
    payload = {"data": {"summary": {"Количество": value, "rows": [{"Количество": value}]},
                        "rows": [{"Количество": value}]},
               "rows": [{"Количество": value}]}
    cleaned = sanitize_tool_result(payload, report_mode=True, tool_name="get_report_ai_job_data")
    assert cleaned["data"]["summary"]["Количество"] == REDACTED_PHONE
    assert cleaned["data"]["summary"]["rows"][0]["Количество"] == REDACTED_PHONE
    assert cleaned["rows"][0]["Количество"] == REDACTED_PHONE
    assert cleaned["data"]["rows"][0]["Количество"] == value
    assert sanitize_tool_result({"rows": [{"Количество": value}]}, report_mode=True)["rows"][0]["Количество"] == REDACTED_PHONE


def test_privacy_note_explains_quantity_tradeoff() -> None:
    from web_html import REPORT_PRIVACY_NOTE

    assert "Числовые значения в колонках количества сохраняются" in REPORT_PRIVACY_NOTE
    assert "телефон" in REPORT_PRIVACY_NOTE
    assert "может остаться видимым" in REPORT_PRIVACY_NOTE
    assert "Явно помеченные" in REPORT_PRIVACY_NOTE
