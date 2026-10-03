"""Stage 363 regression guards: deep average scan and first failed-job observation."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import service_metrics
from server import mcp
from tests.test_revenue_summary import BASE, bearer_runtime_patch, billing_mock
from tools.crud_helpers import paginate_all


def _query(request):
    return parse_qs(urlparse(str(request.url)).query)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("count", [10101, 10200])
async def test_average_scans_beyond_ten_thousand_through_real_query_builder(count):
    billing_mock()
    queries = []

    def page(request):
        query = _query(request)
        queries.append(query)
        filters = json.loads(query["filter"][0])
        cursor = [int(item["value"]) for item in filters if item["property"] == "id"]
        start = cursor[0] if cursor else 0
        rows = [{"id": number, "amount": "100.00" if number == count else "1.00"}
                for number in range(start + 1, min(start + 101, count + 1))]
        return httpx.Response(200, json={"success": True, "data": {
            "invoice": rows, "totalCount": count - start,
        }})

    route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_average_invoice", {
            "date_from": "2025-01-01", "date_to": "2025-12-31",
        })
    body = result.structured_content
    assert body["invoices_with_amount"] == count
    assert body["total_amount"] == f"{count + 99:.2f}"
    assert len(route.calls) >= 102
    assert all(query["offset"] == ["0"] for query in queries)
    assert all(json.loads(query["sort"][0]) == [{"property": "id", "direction": "ASC"}] for query in queries)


@pytest.mark.asyncio
@respx.mock
async def test_average_keeps_scanning_after_short_page_with_larger_total():
    billing_mock()
    starts = []

    def page(request):
        filters = json.loads(_query(request)["filter"][0])
        cursor = next((int(f["value"]) for f in filters if f["property"] == "id"), 0)
        starts.append(cursor)
        if cursor == 0:
            return httpx.Response(200, json={"success": True, "data": {"invoice": [{"id": 1, "amount": "1"}], "totalCount": 2}})
        return httpx.Response(200, json={"success": True, "data": {"invoice": [{"id": 2, "amount": "2"}], "totalCount": 1}})

    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        body = (await mcp.call_tool("get_average_invoice", {"date_from": "2025-01-01", "date_to": "2025-12-31"})).structured_content
    assert starts == [0, 1]
    assert body["invoices_with_amount"] == 2
    assert body["total_amount"] == "3.00"


@pytest.mark.asyncio
@respx.mock
async def test_keyset_ignores_low_total_on_full_page_and_rejects_premature_empty():
    billing_mock()

    def page(request):
        filters = json.loads(_query(request)["filter"][0]) if "filter" in _query(request) else []
        cursor = next((int(f["value"]) for f in filters if f["property"] == "id"), 0)
        if cursor == 0:
            rows, total = [{"id": 1}, {"id": 2}], 1
        elif cursor == 2:
            rows, total = [{"id": 3}], 2
        else:
            rows, total = [], 1
        return httpx.Response(200, json={"success": True, "data": {"invoice": rows, "totalCount": total}})

    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="pagination ended before totalCount"):
        await paginate_all("/rest/api/invoice", entity_key="invoice", page_size=2,
                           keyset_id=True, max_rows=None)


@pytest.mark.asyncio
@respx.mock
async def test_public_invoice_offset_limit_is_unchanged():
    billing_mock()
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="10000"):
        await mcp.call_tool("get_invoices", {"offset": 10001})


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("tool,args,path", [
    ("confirm_report_ai_job_candidate", {"job_id": 363, "report_id": 7}, "confirm"),
    ("reject_report_ai_job_candidate", {"job_id": 363}, "reject"),
    ("save_report_ai_job_as_report", {"job_id": 363, "title": "MCP invoices for May 2026"}, "save"),
])
async def test_failed_mutation_records_code_once_before_status(tool, args, path):
    billing_mock()
    job = {"id": 363, "status": "failed", "error_code": "SAVE_FAILED"}
    respx.post(f"{BASE}/rest/api/report-ai-job/363/{path}").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": job}})
    )
    respx.get(f"{BASE}/rest/api/report-ai-job/363").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": job}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool(tool, args)
        first = service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"]
        await mcp.call_tool("get_report_ai_job", {"job_id": 363})
        second = service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"]
    assert first == {"status|SAVE_FAILED": 1}
    assert second == first


@pytest.mark.asyncio
@respx.mock
async def test_failed_mutation_normalizes_unknown_code():
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/364/reject").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": {
            "id": 364, "status": "failed", "error_code": "SQL SELECT secret",
        }}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 364})
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        "status|unknown": 1,
    }
