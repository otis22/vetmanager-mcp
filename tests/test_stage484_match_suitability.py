"""Stage 484: explicit unreadability fails closed; empty data remains valid."""
import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.test_stage170_report_ai_tools import BASE, billing_mock, bearer_runtime_patch


@pytest.mark.asyncio
@pytest.mark.parametrize("data", [None, {"columns": [], "total": 0}, {"rows": "broken"}])
@respx.mock
async def test_unreadable_report_data_fails_closed(data):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/484/data").mock(
        return_value=httpx.Response(200, json={"success": True, "data": data})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="Report AI data is unavailable"):
        await mcp.call_tool("get_report_ai_job_data", {"job_id": 484})


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("link", ["https://unexpected.example/report",
                                  pytest.param(123, id="non-string-int"),
                                  pytest.param([], id="non-string-list"),
                                  pytest.param({}, id="non-string-object"),
                                  "/rest/api/report/../private",
                                  "/rest/api/report/%2e%2e/private",
                                  "/rest/api/report/%252e%252e/private",
                                  "/rest/api/report/%25252e%25252e/private",
                                  "/rest/api/report/startReport?note=%0A",
                                  "/rest/api/report/startReport%23fragment",
                                  "/rest/api/report/startReport#",
                                  "/rest/api/report/startReport?note=%E2%80%A8",
                                  "/rest/api/report/startReport?note=%E2%80%AE",
                                  pytest.param("/rest/api/report/startReport?note=\u00a0", id="invisible-nbsp"),
                                  pytest.param("/rest/api/report/startReport?note=%C2%A0", id="encoded-nbsp"),
                                  pytest.param("/rest/api/report/startReport?note=\u3000", id="ideographic-space"),
                                  pytest.param("/rest/api/report/startReport?note=\ue000", id="private-use")])
async def test_broken_report_data_link_fails_closed(link):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/484/data").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {
            "columns": [], "rows": [], "total": 0,
            "csv_export_url": link,
        }})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="Report AI data is unavailable"):
        await mcp.call_tool("get_report_ai_job_data", {"job_id": 484})


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("link", [None, "", "/rest/api/report/startReport?report_id=84"])
async def test_valid_empty_matched_report_keeps_empty_result(link):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/484/data").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {
            "columns": [], "rows": [], "total": 0, "limited": False,
            "csv_export_url": link,
        }})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        response = await mcp.call_tool("get_report_ai_job_data", {"job_id": 484})
    assert route.call_count == 1
    assert response.structured_content["data"]["rows"] == []
    assert response.structured_content["data"]["total"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_non_object_report_data_fails_closed():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/484/data").mock(
        return_value=httpx.Response(200, json=[])
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="Report AI data is unavailable"):
        await mcp.call_tool("get_report_ai_job_data", {"job_id": 484})


@pytest.mark.asyncio
@respx.mock
async def test_readable_rows_survive_nonfinite_total():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/484/data").mock(
        return_value=httpx.Response(200, content=b'{"success":true,"data":{"rows":[],"total":Infinity}}',
                                    headers={"content-type": "application/json"})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        response = await mcp.call_tool("get_report_ai_job_data", {"job_id": 484})
    assert response.structured_content["data"]["rows"] == []
