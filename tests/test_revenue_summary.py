import json
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from fastmcp.exceptions import ToolError
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
            {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
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
async def test_get_payments_date_range_matches_revenue_summary_received_boundaries():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "payment": [
                        {
                            "id": 1,
                            "amount": "100.00",
                            "status": "exec",
                            "create_date": "2026-03-15 10:00:00",
                        }
                    ],
                }
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_payments",
            {
                "date_from": "2026-03-01",
                "date_to": "2026-03-31",
                "status": "exec",
            },
        )
        await mcp.call_tool(
            "get_revenue_summary",
            {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
        )

    payments_filters = _filters_from_call(route.calls[0])
    summary_filters = _filters_from_call(route.calls[1])

    def create_date_bounds(filters: list[dict]) -> set[tuple[str, str]]:
        return {
            (f["operator"], f["value"])
            for f in filters
            if f["property"] == "create_date"
        }

    expected = {
        (">=", "2026-03-01 00:00:00"),
        ("<", "2026-04-01 00:00:00"),
    }
    assert create_date_bounds(payments_filters) == expected
    assert create_date_bounds(summary_filters) == expected


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
            {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
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
            {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
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
                {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
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
                {"date_from": "2026-03-01", "date_to": "2026-03-31", "mode": "received"},
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


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_defaults_to_invoice_date_exec_half_open():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 2,
                    "invoice": [
                        {"id": 1, "amount": "1000.00", "status": "exec"},
                        {"id": 2, "amount": "500.00", "status": "exec"},
                    ],
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_average_invoice",
            {"date_from": "2026-06-17", "date_to": "2026-06-17"},
        )

    data = result.structured_content
    assert data["date_basis"] == "invoice_date"
    assert data["date_field"] == "invoice_date"
    assert data["status"] == "exec"
    assert data["invoices_with_amount"] == 2
    assert data["total_revenue"] == 1500.0
    assert data["average_invoice"] == 750.0
    assert data["warnings"] == []
    actual = {(f["property"], f["operator"], f["value"]) for f in _filters_from_call(route.calls[0])}
    assert ("invoice_date", ">=", "2026-06-17 00:00:00") in actual
    assert ("invoice_date", "<", "2026-06-18 00:00:00") in actual
    assert ("status", "=", "exec") in actual


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_scans_more_than_ten_thousand_without_losing_weight():
    billing_mock()

    def invoice_page(request):
        query = _query_from_call(type("Call", (), {"request": request})())
        offset = int(query["offset"][0])
        rows = [
            {"id": number + 1, "amount": "1.00" if number < 10000 else "100.00"}
            for number in range(offset, min(offset + 100, 10001))
        ]
        return httpx.Response(200, json={"success": True, "data": {
            "totalCount": 10001, "invoice": rows,
        }})

    route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_page)
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_average_invoice", {
            "date_from": "2025-09-25", "date_to": "2026-09-25",
        })

    data = result.structured_content
    assert data["invoices_with_amount"] == 10001
    assert data["total_amount"] == "10100.00"
    assert data["total_revenue"] == 10100.0
    assert data["average_invoice"] == 1.01
    assert len(route.calls) >= 101


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["page_budget", "time_budget", "network"])
async def test_get_average_invoice_never_returns_partial_total(failure):
    import tools.invoice as invoice_module

    async def incomplete_scan(*args, **kwargs):
        assert kwargs["max_calls"] == 1000
        assert kwargs["max_rows"] is None
        assert kwargs["collect"] is False
        assert "No partial result" in kwargs["call_budget_error"]
        kwargs["on_page"]([{"id": 1, "amount": "99.00"}])
        if failure == "page_budget":
            raise ToolError(kwargs["call_budget_error"])
        if failure == "time_budget":
            raise TimeoutError()
        raise ToolError("upstream unavailable")

    headers_patch, runtime_patch = bearer_runtime_patch()
    with patch.object(invoice_module, "paginate_all", incomplete_scan), headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_average_invoice", {
                "date_from": "2026-06-17", "date_to": "2026-06-18",
            })
    message = str(exc_info.value)
    assert "99.00" not in message
    if failure == "network":
        assert "upstream unavailable" in message
    else:
        assert "No partial result" in message
        assert "total_amount" in message
        assert "invoices_with_amount" in message


@pytest.mark.asyncio
async def test_get_average_invoice_single_day_budget_gives_cursor_path():
    import tools.invoice as invoice_module

    async def budget(*args, **kwargs):
        raise ToolError(kwargs["call_budget_error"])

    headers_patch, runtime_patch = bearer_runtime_patch()
    with patch.object(invoice_module, "paginate_all", budget), headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_average_invoice", {
                "date_from": "2026-06-17", "date_to": "2026-06-17",
            })
    assert "get_invoices" in str(exc_info.value)
    assert "id > last seen id" in str(exc_info.value)


@pytest.mark.asyncio
async def test_get_average_invoice_enforces_elapsed_time_budget():
    import tools.invoice as invoice_module

    class ExpiredBudget:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            raise TimeoutError()

    async def one_page(*args, **kwargs):
        kwargs["on_page"]([{"id": 1, "amount": "99.00"}])
        return [], 1

    headers_patch, runtime_patch = bearer_runtime_patch()
    with (
        patch.object(invoice_module, "paginate_all", one_page),
        patch.object(invoice_module.asyncio, "timeout", side_effect=lambda seconds: ExpiredBudget()) as timer,
        headers_patch,
        runtime_patch,
    ):
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_average_invoice", {
                "date_from": "2026-06-17", "date_to": "2026-06-18",
            })
    assert timer.call_args.args == (300,)
    assert "No partial result" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_parts_combine_by_sum_and_count():
    billing_mock()

    def invoice_page(request):
        query = parse_qs(urlparse(str(request.url)).query)
        filters = json.loads(query["filter"][0])
        start = next(f["value"] for f in filters if f["operator"] == ">=")
        amounts = ["1.00", "1.00"] if start.startswith("2026-06-17") else ["100.00"]
        rows = [{"id": idx + 1, "amount": amount} for idx, amount in enumerate(amounts)]
        return httpx.Response(200, json={"success": True, "data": {
            "invoice": rows, "totalCount": len(rows),
        }})

    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_page)
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        first = (await mcp.call_tool("get_average_invoice", {
            "date_from": "2026-06-17", "date_to": "2026-06-17",
        })).structured_content
        second = (await mcp.call_tool("get_average_invoice", {
            "date_from": "2026-06-18", "date_to": "2026-06-18",
        })).structured_content
    total = sum(float(part["total_amount"]) for part in (first, second))
    count = sum(part["invoices_with_amount"] for part in (first, second))
    assert (total, count, round(total / count, 2)) == (102.0, 3, 34.0)
    assert (first["average_invoice"] + second["average_invoice"]) / 2 != 34.0


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_create_date_preserves_no_status_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "invoice": [{"id": 1, "amount": "900.00", "status": "save"}],
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_average_invoice",
            {
                "date_from": "2026-06-17",
                "date_to": "2026-06-17",
                "date_basis": "create_date",
            },
        )

    data = result.structured_content
    assert data["date_basis"] == "create_date"
    assert data["date_field"] == "create_date"
    assert data["status"] == ""
    assert data["average_invoice"] == 900.0
    assert data["warnings"]
    actual = {(f["property"], f["operator"], f["value"]) for f in _filters_from_call(route.calls[0])}
    assert ("create_date", ">=", "2026-06-17 00:00:00") in actual
    assert ("create_date", "<", "2026-06-18 00:00:00") in actual
    assert not any(f[0] == "status" for f in actual)


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_rejects_invalid_date_basis_before_http():
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"invoice": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_average_invoice",
                {
                    "date_from": "2026-06-17",
                    "date_to": "2026-06-17",
                    "date_basis": "payment_create_date",
                },
            )

    assert "date_basis" in str(exc_info.value)
    assert not route.called
