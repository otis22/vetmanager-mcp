import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_ANALYTICS_READ


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(*, scopes=(SCOPE_ANALYTICS_READ,)):
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        scopes=scopes,
    )


def _structured(result) -> dict:
    return result.structured_content


@pytest.mark.asyncio
async def test_report_export_tools_registered_without_list_tool():
    names = {tool.name for tool in await mcp.list_tools()}

    assert "start_report_export" in names
    assert "get_report_export_file" in names
    assert "get_report_ai_job_export" in names
    assert "list_reports" not in names
    assert "get_reports" not in names


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_calls_startreport_without_empty_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "message": "", "data": {"report": {"report_file_id": 123}}},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("start_report_export", {"report_id": 88})

    assert route.call_count == 1
    params = dict(route.calls.last.request.url.params)
    assert params == {"report_id": "88"}
    assert _structured(result)["data"]["report"]["report_file_id"] == 123


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_passes_non_empty_json_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "message": "", "data": {"report": {"report_file_id": 124}}},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "start_report_export",
            {"report_id": 88, "filter_json": "{\"period\":\"2026-06\"}"},
        )

    assert dict(route.calls.last.request.url.params) == {
        "filter": "{\"period\":\"2026-06\"}",
        "report_id": "88",
    }


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_rejects_invalid_filter_before_upstream():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"data": {"unexpected": True}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="filter_json"):
            await mcp.call_tool(
                "start_report_export",
                {"report_id": 88, "filter_json": "{bad json"},
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_error_does_not_echo_filter_json():
    billing_mock()
    secret_filter = "{\"token\":\"do-not-echo\"}"
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        side_effect=httpx.ConnectError("network down")
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool(
                "start_report_export",
                {"report_id": 88, "filter_json": secret_filter},
            )

    assert route.call_count == 1
    assert "do-not-echo" not in str(exc_info.value)
    assert "filter" not in str(exc_info.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_does_not_retry_non_idempotent_get():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        side_effect=[
            httpx.Response(503, json={"success": False, "message": "temporary"}),
            httpx.Response(200, json={"data": {"report": {"report_file_id": 123}}}),
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="Starting report export failed HTTP 503"):
            await mcp.call_tool("start_report_export", {"report_id": 88})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_rejects_200_without_report_file_id():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"report": {}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="report_file_id"):
            await mcp.call_tool("start_report_export", {"report_id": 88})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_report_export_gets_bypass_cache_for_start_and_poll():
    billing_mock()
    start_route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"report": {"report_file_id": 123}}}),
            httpx.Response(200, json={"data": {"report": {"report_file_id": 124}}}),
        ]
    )
    file_route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"report": {"csv_file": "first.csv"}}}),
            httpx.Response(200, json={"data": {"report": {"csv_file": "second.csv"}}}),
        ]
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        first_start = await mcp.call_tool("start_report_export", {"report_id": 88})
        second_start = await mcp.call_tool("start_report_export", {"report_id": 88})
        first_file = await mcp.call_tool("get_report_export_file", {"report_file_id": 123})
        second_file = await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    assert start_route.call_count == 2
    assert file_route.call_count == 2
    assert _structured(first_start)["data"]["report"]["report_file_id"] == 123
    assert _structured(second_start)["data"]["report"]["report_file_id"] == 124
    assert _structured(first_file)["data"]["report"]["csv_file"] == "first.csv"
    assert _structured(second_file)["data"]["report"]["csv_file"] == "second.csv"


@pytest.mark.asyncio
@respx.mock
async def test_get_report_export_file_calls_reportfile_with_file_id():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "",
                "data": {
                    "report": {
                        "html_file": "report.html",
                        "csv_file": "report.csv",
                        "csv_semicolon_file": "report-semicolon.csv",
                        "xlsx_file": "report.xlsx",
                    }
                },
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    assert dict(route.calls.last.request.url.params) == {"file_id": "123"}
    assert _structured(result)["data"]["report"]["csv_file"] == "report.csv"


@pytest.mark.asyncio
@respx.mock
async def test_get_report_export_file_turns_not_ready_into_retry_guidance():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(
            401,
            json={"success": False, "message": "Error: build in progress."},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="not ready.*get_report_export_file"):
            await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_report_export_file_treats_409_as_retryable_without_message():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(409, json={"success": False, "message": ""})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="not ready.*get_report_export_file"):
            await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_report_export_file_rejects_200_without_export_fields():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"report": {}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="export file fields"):
            await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_start_report_export_missing_scope_keeps_scope_error():
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"data": {"report": {"report_file_id": 123}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=())
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool("start_report_export", {"report_id": 88})

    message = str(exc_info.value)
    assert "Required scopes: analytics.read" in message
    assert "Missing scopes: analytics.read" in message
    assert "not REST-exportable" not in message
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_report_export_file_missing_scope_keeps_scope_error():
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(
        return_value=httpx.Response(200, json={"data": {"report": {"csv_file": "secret.csv"}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch(scopes=())
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool("get_report_export_file", {"report_file_id": 123})

    message = str(exc_info.value)
    assert "Required scopes: analytics.read" in message
    assert "Missing scopes: analytics.read" in message
    assert "not REST-exportable" not in message
    assert "secret.csv" not in message
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "status",
    ["queued", "recognizing", "building_preview", "needs_confirmation", "ready_to_save", "failed", "rejected"],
)
async def test_get_report_ai_job_export_rejects_non_exportable_statuses_before_startreport(status):
    billing_mock()
    job_route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"job": {"id": 22, "status": status, "report_id": 88}}},
        )
    )
    start_route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"data": {"report": {"report_file_id": 123}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="saved or existing_report_matched"):
            await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})

    assert job_route.call_count == 1
    assert start_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_export_rejects_malformed_job_report_id():
    billing_mock()
    job_route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"job": {"id": 22, "status": "saved", "report_id": "bad"}}},
        )
    )
    start_route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"data": {"report": {"report_file_id": 123}}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="report_id"):
            await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})

    assert job_route.call_count == 1
    assert start_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_export_starts_export_for_saved_job_report_id():
    billing_mock()
    job_route = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"job": {"id": 22, "status": "saved", "report_id": 88}}},
        )
    )
    start_route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"report": {"report_file_id": 123}}},
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})

    assert job_route.call_count == 1
    assert dict(start_route.calls.last.request.url.params) == {"report_id": "88"}
    assert _structured(result)["data"]["report"]["report_file_id"] == 123


@pytest.mark.asyncio
@respx.mock
async def test_get_report_ai_job_export_surfaces_403_as_not_rest_exportable():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"job": {"id": 22, "status": "existing_report_matched", "report_id": 88}}},
        )
    )
    start_route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(403, json={"success": False, "message": "not accessible"})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="not REST-exportable"):
            await mcp.call_tool("get_report_ai_job_export", {"job_id": 22})

    assert start_route.call_count == 1
