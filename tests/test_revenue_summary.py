import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _query_from_call(call) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(call.request.url)).query)


def _filters_from_call(call) -> list[dict]:
    q = _query_from_call(call)
    assert "filter" in q, f"no filter param in {call.request.url}"
    return json.loads(q["filter"][0])


def _sort_from_call(call) -> list[dict]:
    q = _query_from_call(call)
    assert "sort" in q, f"no sort param in {call.request.url}"
    return json.loads(q["sort"][0])


@pytest.mark.asyncio
@respx.mock
async def test_get_payments_status_filter_and_invalid_status():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "payment": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_payments", {"status": "exec"})
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_payments", {"status": "paid"})

    filters = _filters_from_call(route.calls[0])
    assert any(
        f["property"] == "status" and f["operator"] == "=" and f["value"] == "exec"
        for f in filters
    )
    assert "status" in str(exc_info.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_received_uses_exec_payments_and_half_open_dates():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 2,
                    "payment": [
                        {
                            "id": 1,
                            "amount": "100.10",
                            "status": "exec",
                            "create_date": "2026-03-01 10:00:00",
                        },
                        {
                            "id": 2,
                            "amount": "200.20",
                            "status": "exec",
                            "create_date": "2026-03-31 23:59:59",
                        },
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {"date_from": "2026-03-01", "date_to": "2026-03-31"},
        )

    data = result.structured_content
    assert data["success"] is True
    assert data["mode"] == "received"
    assert data["source"] == "payment"
    assert data["total_amount"] == "300.30"
    assert data["returned_count"] == 2
    assert data["scanned_count"] == 2
    assert data["total_count"] == 2
    assert data["page_cap"] == 20
    assert data["page_size"] == 100
    assert data["truncated"] is False
    assert data["warnings"] == []
    assert data["by_day"] == [
        {"date": "2026-03-01", "total_amount": "100.10", "count": 1},
        {"date": "2026-03-31", "total_amount": "200.20", "count": 1},
    ]

    filters = _filters_from_call(route.calls[0])
    expected = {
        ("status", "=", "exec"),
        ("create_date", ">=", "2026-03-01 00:00:00"),
        ("create_date", "<", "2026-04-01 00:00:00"),
    }
    actual = {(f["property"], f["operator"], f["value"]) for f in filters}
    assert expected <= actual
    assert _sort_from_call(route.calls[0]) == [{"property": "id", "direction": "ASC"}]


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_invoice_modes_use_invoice_date_and_non_cashflow_label():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "invoice": [
                        {
                            "id": 7,
                            "amount": "500.00",
                            "paid_amount": "300.00",
                            "status": "exec",
                            "invoice_date": "2026-03-15 12:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "mode": "paid_by_executed_invoices",
                "include_breakdown": False,
            },
        )
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_revenue_summary",
                {
                    "date_from": "2026-03-01",
                    "date_to": "2026-03-31",
                    "mode": "paid_by_invoices",
                },
            )

    data = result.structured_content
    assert data["total_amount"] == "300.00"
    assert data["source"] == "invoice"
    assert data["cashflow"] is False
    assert data["by_day"] == []
    filters = _filters_from_call(route.calls[0])
    actual = {(f["property"], f["operator"], f["value"]) for f in filters}
    assert ("status", "=", "exec") in actual
    assert ("invoice_date", ">=", "2026-03-01 00:00:00") in actual
    assert ("invoice_date", "<", "2026-04-01 00:00:00") in actual
    assert "mode" in str(exc_info.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_invoiced_mode_uses_invoice_amount():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "invoice": [
                        {
                            "id": 8,
                            "amount": "500.00",
                            "paid_amount": "300.00",
                            "status": "exec",
                            "invoice_date": "2026-03-15 12:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "mode": "invoiced",
            },
        )

    data = result.structured_content
    assert data["mode"] == "invoiced"
    assert data["amount_field"] == "amount"
    assert data["total_amount"] == "500.00"
    assert data["cashflow"] is False
    assert data["by_day"] == [
        {"date": "2026-03-15", "total_amount": "500.00", "count": 1}
    ]
    filters = _filters_from_call(route.calls[0])
    actual = {(f["property"], f["operator"], f["value"]) for f in filters}
    assert ("status", "=", "exec") in actual
    assert ("invoice_date", ">=", "2026-03-01 00:00:00") in actual
    assert ("invoice_date", "<", "2026-04-01 00:00:00") in actual


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_truncated_warns_partial_totals():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 2500,
                    "payment": [
                        {
                            "id": i,
                            "amount": "1.00",
                            "status": "exec",
                            "create_date": "2026-03-01 10:00:00",
                        }
                        for i in range(100)
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {"date_from": "2026-03-01", "date_to": "2026-03-31"},
        )

    data = result.structured_content
    assert data["truncated"] is True
    assert data["scanned_count"] == 2000
    assert data["total_count"] == 2500
    assert data["total_amount"] == "2000.00"
    assert data["warnings"]
    assert "partial" in data["warnings"][0].lower()
    assert len(route.calls) == 20


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_exact_page_cap_is_not_truncated_when_total_known():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 2000,
                    "payment": [
                        {
                            "id": i,
                            "amount": "1.00",
                            "status": "exec",
                            "create_date": "2026-03-01 10:00:00",
                        }
                        for i in range(100)
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_revenue_summary",
            {"date_from": "2026-03-01", "date_to": "2026-03-31"},
        )

    data = result.structured_content
    assert data["truncated"] is False
    assert data["warnings"] == []
    assert data["scanned_count"] == 2000
    assert data["total_count"] == 2000
    assert data["total_amount"] == "2000.00"
    assert len(route.calls) == 20


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_rejects_malformed_amounts_before_total():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "payment": [
                        {
                            "id": 77,
                            "amount": "not-money",
                            "status": "exec",
                            "create_date": "2026-03-01 10:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_revenue_summary",
                {"date_from": "2026-03-01", "date_to": "2026-03-31"},
            )

    assert "amount" in str(exc_info.value)
    assert "77" in str(exc_info.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_rejects_non_finite_amounts_before_total():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "payment": [
                        {
                            "id": 78,
                            "amount": "NaN",
                            "status": "exec",
                            "create_date": "2026-03-01 10:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_revenue_summary",
                {"date_from": "2026-03-01", "date_to": "2026-03-31"},
            )

    assert "amount" in str(exc_info.value)
    assert "78" in str(exc_info.value)
    assert len(route.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_revenue_summary_rejects_invalid_dates_before_http():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "payment": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_revenue_summary",
                {"date_from": "2026-04-01", "date_to": "2026-03-01"},
            )
    assert "date_from" in str(exc_info.value)
    assert not route.called
