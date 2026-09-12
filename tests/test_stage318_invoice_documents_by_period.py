"""Stage 318 guards for bounded period invoice-document collection."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def _runtime_patch():
    return patch_runtime_credentials(DOMAIN, API_KEY, bearer_token="mock-token")


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _query(request: httpx.Request) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(request.url)).query)


@pytest.mark.asyncio
@respx.mock
async def test_period_tool_reads_whole_batches_before_global_page_and_never_sends_over_500_ids():
    """Guard: changing the safe batch constant above 500 makes this test red."""
    _billing_mock()
    invoices = [
        {"id": invoice_id, "invoice_date": "2026-09-12 10:00:00"}
        for invoice_id in range(1, 552)
    ]

    def invoice_response(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        offset = int(query["offset"][0])
        return httpx.Response(200, json={"data": {
            "invoice": invoices[offset:offset + 100], "totalCount": len(invoices),
        }})

    document_batch_sizes: list[int] = []

    def document_response(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        filters = json.loads(query["filter"][0])
        ids = filters[0]["value"]
        document_batch_sizes.append(len(ids))
        offset = int(query["offset"][0])
        rows = [
            {"id": invoice_id, "document_id": invoice_id, "good_id": 10}
            for invoice_id in ids
        ]
        return httpx.Response(200, json={"data": {
            "invoiceDocument": rows[offset:offset + 100], "totalCount": len(rows),
        }})

    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_response)
    document_route = respx.get(f"{BASE}/rest/api/invoiceDocument").mock(side_effect=document_response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoice_documents_by_period", {
            "date_from": "2026-09-12", "date_to": "2026-09-12", "limit": 25, "offset": 490,
        })

    data = result.structured_content["data"]
    assert data["limited"] is False
    assert data["totalCount"] == 551
    assert [row["invoice_id"] for row in data["invoiceDocument"]] == list(range(491, 516))
    assert all(size <= 500 for size in document_batch_sizes)
    assert max(document_batch_sizes) == 500
    assert len(invoice_route.calls) == 6
    assert len(document_route.calls) == 6
    assert all(
        json.loads(_query(call.request)["sort"][0]) == [
            {"property": "document_id", "direction": "ASC"},
            {"property": "id", "direction": "ASC"},
        ]
        for call in document_route.calls
    )


@pytest.mark.asyncio
@respx.mock
async def test_period_tool_marks_scan_limited_when_invoice_pages_consume_budget():
    _billing_mock()
    invoices = [{"id": item, "invoice_date": "2026-09-12 10:00:00"} for item in range(1, 2002)]

    def invoice_response(request: httpx.Request) -> httpx.Response:
        offset = int(_query(request)["offset"][0])
        return httpx.Response(200, json={"data": {
            "invoice": invoices[offset:offset + 100], "totalCount": len(invoices),
        }})

    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_invoice_documents_by_period", {
            "date_from": "2026-09-12", "date_to": "2026-09-12",
        })

    data = result.structured_content["data"]
    assert data["limited"] is True
    assert data["limited_reason"] == "upstream_call_budget"
    assert data["next_offset"] is None
    assert data["upstream_calls"] == 20
    assert len(invoice_route.calls) == 20


@pytest.mark.asyncio
async def test_period_tool_rejects_negative_offset_before_upstream_call():
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="offset must be 0 or greater"):
            await mcp.call_tool("get_invoice_documents_by_period", {
                "date_from": "2026-09-12", "date_to": "2026-09-12", "offset": -1,
            })
