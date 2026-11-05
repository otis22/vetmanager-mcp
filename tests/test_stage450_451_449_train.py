"""Regression guards for release train 450, 451, 449."""

import httpx
import pytest
import respx
import re

from depersonalization import REDACTED_PHONE, sanitize_report_cell, sanitize_tool_result
from exceptions import AuthError
from identifier_aliases import normalize_arguments
from report_export import build_export_csv
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tests.runtime_factories import patch_runtime_credentials
from fastmcp.exceptions import ToolError
from tools.report_ai import _tool_error_from_vm


def test_csv_money_matches_report_ai_row_and_keeps_phone_mask():
    amount = "246800.0000000000"
    report_row = sanitize_tool_result(
        {"data": {"columns": ["Сумма", "Примечание"],
                  "rows": [{"Сумма": amount, "Примечание": "тел. 9123456789"}]}},
        report_mode=True, tool_name="get_report_ai_job_data",
    )["data"]["rows"][0]
    csv_text, _, _ = build_export_csv(
        f'Сумма,Примечание\n{amount},"тел. 9123456789"\n'.encode(),
        delimiter=",", depersonalize=True,
    )
    assert report_row["Сумма"] == amount
    assert sanitize_report_cell("Сумма", amount) == amount
    assert amount in csv_text and REDACTED_PHONE in csv_text
    assert "9123456789" not in csv_text
    assert sanitize_report_cell("Сумма", "89161234567") == REDACTED_PHONE
    assert sanitize_report_cell("Телефон", amount) == REDACTED_PHONE


@pytest.mark.parametrize("amount", ["246800.0000000000", "246800,0000000000"])
def test_money_decimal_separator_is_preserved_in_csv(amount):
    csv_text, _, _ = build_export_csv(
        f'Сумма;Контакт\n"{amount}";"+7 999 123-45-67"\n'.encode(),
        delimiter=";", depersonalize=True,
    )
    assert amount in csv_text
    assert REDACTED_PHONE in csv_text


def test_fixed_decimal_quantity_matches_job_data_and_csv():
    value = "123456.0000000000"
    row = sanitize_tool_result(
        {"data": {"columns": ["Количество"], "rows": [{"Количество": value}]}},
        report_mode=True, tool_name="get_report_ai_job_data",
    )["data"]["rows"][0]
    csv_text, _, _ = build_export_csv(
        f"Количество\n{value}\n".encode(), delimiter=",", depersonalize=True,
    )
    assert row["Количество"] == value
    assert value in csv_text


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("tool,method,path,args", [
    ("create_report_ai_job", "post", "/rest/api/report-ai-job", {"intent_text": "Сводка за май"}),
    ("get_report_ai_job", "get", "/rest/api/report-ai-job/22", {"job_id": 22}),
])
async def test_report_ai_forbidden_code_is_actionable(tool, method, path, args):
    billing_mock()
    getattr(respx, method)(f"{BASE}{path}").mock(return_value=httpx.Response(
        403, json={"data": {"error_code": "FORBIDDEN"}, "message": "private upstream text"},
    ))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(Exception) as raised:
        await mcp.call_tool(tool, args)
    message = str(raised.value)
    assert "Report AI request failed (FORBIDDEN)" in message
    assert "Check access to Report AI with the clinic administrator" in message
    assert "private upstream text" not in message


def test_explicit_forbidden_error_code_has_same_access_guidance():
    error = AuthError("private upstream text", status_code=403, error_code="FORBIDDEN")
    message = str(_tool_error_from_vm(error))
    assert "Check access to Report AI with the clinic administrator" in message
    assert "private upstream text" not in message


def test_id_alias_is_scoped_to_by_id_tools():
    assert normalize_arguments({"id": 7}, tool_name="get_admissions") == {"id": 7}
    assert normalize_arguments({"id": 7}, tool_name="get_medical_card_by_id") == {"id": 7}


@pytest.mark.asyncio
async def test_every_by_id_accepts_id_without_changing_published_schema():
    for tool in await mcp.list_tools():
        if not tool.name.endswith("_by_id"):
            continue
        properties = tool.to_mcp_tool().inputSchema["properties"]
        if "id" in properties:
            assert tool.name == "get_medical_card_by_id"
            assert normalize_arguments({"id": 7}, tool_name=tool.name) == {"id": 7}
            continue
        primary = [name for name in properties if name.endswith("_id")]
        assert len(primary) == 1, tool.name
        primary = primary[0]
        assert "id" not in properties
        assert normalize_arguments({"id": 7}, tool_name=tool.name) == {primary: 7}
        assert normalize_arguments({"id": 7, primary: 7}, tool_name=tool.name) == {primary: 7}
        with pytest.raises(ToolError, match=primary):
            normalize_arguments({"id": 7, primary: 8}, tool_name=tool.name)
        with pytest.raises(ToolError, match=primary):
            normalize_arguments({"id": "7", primary: 7}, tool_name=tool.name)
        with pytest.raises(ToolError, match=primary):
            normalize_arguments({"id": True, primary: 1}, tool_name=tool.name)


@pytest.mark.asyncio
@respx.mock
async def test_admission_by_id_alias_reaches_rest_and_conflict_does_not():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission/7").mock(return_value=httpx.Response(
        200, json={"data": {"id": 7}},
    ))
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_admission_by_id", {"id": 7})
        assert result.structured_content["data"]["id"] == 7
        with pytest.raises(ToolError, match="admission_id"):
            await mcp.call_tool("get_admission_by_id", {"id": 7, "admission_id": 8})
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_every_new_by_id_alias_crosses_mcp_validation():
    billing_mock()
    route = respx.get(re.compile(r"https://testclinic\.vetmanager\.cloud/rest/api/.*")).mock(
        return_value=httpx.Response(404, json={"message": "not found"}),
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1,
        connection_id=1,
    )
    with headers, runtime:
        for tool in await mcp.list_tools():
            if not tool.name.endswith("_by_id") or tool.name == "get_medical_card_by_id":
                continue
            before = route.call_count
            try:
                await mcp.call_tool(tool.name, {"id": 999999999})
            except Exception:
                pass  # The mocked REST response is 404; validation must have passed.
            assert route.call_count == before + 1, tool.name
            assert "999999999" in str(route.calls.last.request.url), tool.name
