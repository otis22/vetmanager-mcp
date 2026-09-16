"""Stage 323 guards: complete scans, globally honest merges, strict envelopes."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from tools.crud_helpers import paginate_all

DOMAIN = "testclinic"
API_KEY = "test-key-stage323"
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
@pytest.mark.parametrize("bad_total", [None, "2", 1.5, True, -1])
async def test_paginate_all_treats_absent_or_invalid_total_as_unknown(bad_total):
    _billing_mock()
    calls = 0

    def response(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        rows = [{"id": 1}, {"id": 2}] if calls == 1 else [{"id": 3}]
        data = {"client": rows}
        if bad_total is not None:
            data["totalCount"] = bad_total
        return httpx.Response(200, json={"success": True, "data": data})

    respx.get(f"{BASE}/rest/api/client").mock(side_effect=response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        rows, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=2,
        )

    assert [row["id"] for row in rows] == [1, 2, 3]
    assert total == 3
    assert calls == 2


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_ignores_low_total_on_full_page_and_uses_id_tiebreaker():
    _billing_mock()
    calls = 0
    route = respx.get(f"{BASE}/rest/api/client")

    def response(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        rows = [{"id": 1}, {"id": 2}] if calls == 1 else [{"id": 3}]
        return httpx.Response(200, json={
            "success": True,
            "data": {"client": rows, "totalCount": 1},
        })

    route.mock(side_effect=response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        rows, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=2,
        )

    assert [row["id"] for row in rows] == [1, 2, 3]
    assert total == 3
    assert json.loads(_query(route.calls[0].request)["sort"][0]) == [
        {"property": "id", "direction": "ASC"}
    ]


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_continues_after_short_page_when_current_total_is_larger():
    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(side_effect=[
        httpx.Response(200, json={"success": True, "data": {
            "client": [{"id": 1}], "totalCount": 2,
        }}),
        httpx.Response(200, json={"success": True, "data": {
            "client": [{"id": 2}], "totalCount": 2,
        }}),
    ])
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        rows, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=100,
        )

    assert [row["id"] for row in rows] == [1, 2]
    assert total == 2
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("payload", [
    {"success": False, "message": "database details must not escape"},
    {"data": {"totalCount": 0, "client": []}},
    {"success": True, "data": "not-an-object"},
    {"success": True, "data": {"totalCount": 1, "client": {"id": 1}}},
])
async def test_paginate_all_rejects_application_errors_and_malformed_envelopes(payload):
    _billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json=payload)
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await paginate_all("/rest/api/client", entity_key="client")
    assert "database details" not in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_rejects_repeated_full_page_without_progress():
    _billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(200, json={
        "success": True,
        "data": {"totalCount": 999, "client": [{"id": 1}, {"id": 2}]},
    }))
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="progress"):
            await paginate_all(
                "/rest/api/client", entity_key="client", page_size=2, max_calls=3,
            )


@pytest.mark.asyncio
@respx.mock
async def test_invoice_closing_merge_reads_both_branches_then_sorts_and_pages():
    _billing_mock()
    minus_rows = [{"id": i, "create_date": "2026-09-16"} for i in range(1, 102)]
    plus_rows = [
        {"id": "101", "create_date": "2026-09-16"},
        *[{"id": i, "create_date": "2026-09-16"} for i in range(102, 203)],
    ]

    def response(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        filters = json.loads(query["filter"][0])
        rows = minus_rows if any(
            item["property"] == "minus_document_id" for item in filters
        ) else plus_rows
        offset = int(query["offset"][0])
        return httpx.Response(200, json={"success": True, "data": {
            "closingOfInvoices": rows[offset:offset + 100],
            "totalCount": 1 if offset == 0 else len(rows),
        }})

    route = respx.get(f"{BASE}/rest/api/closingOfInvoices").mock(side_effect=response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_closing_of_invoices", {
            "invoice_id": 8,
            "limit": 5,
            "offset": 99,
            "sort": [{"property": "create_date", "direction": "DESC"}],
        })

    data = result.structured_content["data"]
    assert [row["id"] for row in data["closingOfInvoices"]] == [100, 101, 102, 103, 104]
    assert data["totalCount"] == 202
    assert data["limited"] is False
    assert route.call_count == 4


@pytest.mark.asyncio
@respx.mock
async def test_user_name_merge_honors_offset_after_complete_global_sort():
    _billing_mock()
    last_rows = [{"id": i, "last_name": "Same"} for i in range(1, 102)]
    first_rows = [
        {"id": "101", "first_name": "Same"},
        *[{"id": i, "first_name": "Same"} for i in range(102, 203)],
    ]

    def response(request: httpx.Request) -> httpx.Response:
        query = _query(request)
        filters = json.loads(query["filter"][0])
        rows = last_rows if any(item["property"] == "last_name" for item in filters) else first_rows
        offset = int(query["offset"][0])
        return httpx.Response(200, json={"success": True, "data": {
            "user": rows[offset:offset + 100], "totalCount": len(rows),
        }})

    route = respx.get(f"{BASE}/rest/api/user").mock(side_effect=response)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {
            "name": "Same", "limit": 5, "offset": 99,
            "sort": [{"property": "last_name", "direction": "ASC"}],
        })

    data = result.structured_content["data"]
    assert [row["id"] for row in data["user"]] == [100, 101, 102, 103, 104]
    assert data["totalCount"] == 202
    assert data["limited"] is False
    assert route.call_count == 4


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("entity", ["invoice", "invoiceDocument"])
@pytest.mark.parametrize("payload", [
    {"success": False, "message": "sensitive upstream detail"},
    {"success": True, "data": "malformed"},
])
async def test_period_scan_rejects_failed_or_malformed_pages(entity, payload):
    _billing_mock()
    if entity == "invoice":
        respx.get(f"{BASE}/rest/api/invoice").mock(
            return_value=httpx.Response(200, json=payload)
        )
    else:
        respx.get(f"{BASE}/rest/api/invoice").mock(return_value=httpx.Response(200, json={
            "success": True,
            "data": {"invoice": [{"id": 7, "invoice_date": "2026-09-16"}], "totalCount": 1},
        }))
        respx.get(f"{BASE}/rest/api/invoiceDocument").mock(
            return_value=httpx.Response(200, json=payload)
        )

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as exc_info:
            await mcp.call_tool("get_invoice_documents_by_period", {
                "date_from": "2026-09-16", "date_to": "2026-09-16",
            })
    assert "sensitive upstream detail" not in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("entity", ["invoice", "invoiceDocument"])
async def test_period_scan_rejects_repeated_full_page(entity):
    _billing_mock()
    invoices = [
        {"id": i, "invoice_date": "2026-09-16"}
        for i in range(1, 101)
    ]
    invoice_payload = {
        "success": True,
        "data": {"invoice": invoices, "totalCount": 200},
    }
    if entity == "invoice":
        respx.get(f"{BASE}/rest/api/invoice").mock(
            return_value=httpx.Response(200, json=invoice_payload)
        )
    else:
        respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=[
            httpx.Response(200, json={"success": True, "data": {
                "invoice": [invoices[0]], "totalCount": 1,
            }}),
        ])
        documents = [
            {"id": i, "document_id": 1}
            for i in range(1, 101)
        ]
        respx.get(f"{BASE}/rest/api/invoiceDocument").mock(
            return_value=httpx.Response(200, json={"success": True, "data": {
                "invoiceDocument": documents, "totalCount": 200,
            }})
        )

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="progress"):
            await mcp.call_tool("get_invoice_documents_by_period", {
                "date_from": "2026-09-16", "date_to": "2026-09-16",
            })
