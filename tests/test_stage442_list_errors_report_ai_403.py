"""Stage 442: actionable list arguments and bare Report AI access refusal."""

from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from exceptions import AuthError, ToolInputError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from tools.report_ai import _tool_error_from_vm
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tests.test_stage384_live import seed_devtr6_bearer


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,example", [
    ("get_admissions", '["id", "client_id", "pet_id"]'),
    ("get_invoices", '["id", "client_id", "amount"]'),
    ("get_clients", '["id", "first_name", "last_name"]'),
])
async def test_csv_fields_get_actionable_error(monkeypatch, tool, example):
    module = __import__({
        "get_admissions": "tools.admission",
        "get_invoices": "tools.invoice",
        "get_clients": "tools.client",
    }[tool], fromlist=["crud_list"])
    mocked = AsyncMock()
    monkeypatch.setattr(module, "crud_list", mocked)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime, pytest.raises(ToolInputError) as raised:
        await mcp.call_tool(tool, {"fields": "id,client_id"})
    message = str(raised.value)
    assert "CSV" in message and "JSON array" in message
    assert example in message
    mocked.assert_not_awaited()


@pytest.mark.asyncio
async def test_csv_filter_uses_real_filter_object_example():
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers, runtime, pytest.raises(ToolInputError) as raised:
        await mcp.call_tool("get_admissions", {"filter": "id,client_id"})
    assert '"property": "id"' in str(raised.value)
    assert '"operator": "="' in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", ["id", "id,client_id", '"id"', ""])
async def test_non_array_fields_strings_are_rejected(value):
    with pytest.raises(ToolInputError, match="JSON array"):
        await mcp.call_tool("get_admissions", {"fields": value})


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["sort", "include"])
async def test_other_shared_list_arguments_have_actionable_array_error(argument):
    with pytest.raises(ToolInputError, match="JSON array") as raised:
        await mcp.call_tool("get_admissions", {argument: "id,client_id"})
    assert "for example" in str(raised.value)
    if argument == "sort":
        assert '"direction": "ASC"' in str(raised.value)


@pytest.mark.asyncio
async def test_valid_fields_array_and_json_array_string_still_work(monkeypatch):
    from tests.test_stage399_list_projection import _call, _patch_list

    _patch_list(monkeypatch, "get_admissions")
    for fields in (["id", "client_id"], '["id", "client_id"]'):
        result = await _call("get_admissions", {"fields": fields})
        assert result["data"]["admission"][0] == {"id": 1, "client_id": 2}


def test_bare_report_ai_403_explains_access_without_upstream_text():
    error = AuthError("private upstream text", status_code=403)
    mapped = _tool_error_from_vm(error)
    assert str(mapped) == (
        "Report AI request failed (FORBIDDEN). "
        "Check access to Report AI with the clinic administrator."
    )
    assert "private" not in str(mapped)


@respx.mock
@pytest.mark.asyncio
async def test_vm_http_403_without_machine_code_surfaces_access_guidance():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(403, json={"message": "private upstream text"})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(Exception) as raised:
        await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert "Report AI request failed (FORBIDDEN). Check access to Report AI" in str(raised.value)
    assert "private upstream text" not in str(raised.value)


def test_explicit_unknown_upstream_403_remains_unknown():
    error = AuthError("private upstream text", status_code=403)
    error.observed_error_code = "FUTURE_PRIVATE_CODE"
    assert "(unknown)" in str(_tool_error_from_vm(error))


def test_bare_401_keeps_current_auth_semantics():
    error = AuthError("Invalid or missing API key", status_code=401)
    assert "FORBIDDEN" not in str(_tool_error_from_vm(error))


@respx.mock
@pytest.mark.asyncio
async def test_vm_http_403_with_explicit_unknown_code_stays_unknown():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(
        403, json={"data": {"error_code": "FUTURE_PRIVATE_CODE"}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(Exception) as raised:
        await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert "(unknown)" in str(raised.value)
    assert "FORBIDDEN" not in str(raised.value)
    assert "FUTURE_PRIVATE_CODE" not in str(raised.value)


def test_live_http_mcp_csv_fields_response(live_server_url, prepared_web_db, monkeypatch):
    """A local real HTTP MCP session proves the agent sees the example."""
    monkeypatch.setenv("TEST_DOMAIN", "stage442")
    monkeypatch.setenv("TEST_API_KEY", "stage442-test-key")
    token = seed_devtr6_bearer()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=30) as client:
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage442-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }).status_code in (200, 202)
        response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
                "name": "get_admissions", "arguments": {"fields": "id,client_id"},
            },
        })
        assert response.status_code == 200
        body = response.text
        assert "JSON array" in body
        assert '[\\"id\\", \\"client_id\\", \\"pet_id\\"]' in body
        print("STAGE442 tools/call HTTP", response.status_code, body)
