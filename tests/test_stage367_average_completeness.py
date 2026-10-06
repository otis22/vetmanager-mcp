"""Stage 367: the average check must expose and verify its scan boundary."""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.test_revenue_summary import BASE, bearer_runtime_patch, billing_mock


def _reply(rows, total):
    data = {"invoice": rows}
    if total is not None:
        data["totalCount"] = total
    return httpx.Response(200, json={"success": True, "data": data})


async def _average():
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        return (await mcp.call_tool("get_average_invoice", {
            "date_from": "2020-01-01", "date_to": "2021-12-31",
        })).structured_content


@pytest.mark.asyncio
@respx.mock
async def test_multiple_invoices_reconcile_count_and_decimal_formula():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=_reply([
            {"id": 1, "amount": "1.004"},
            {"id": 2, "amount": "1.004"},
            {"id": 3, "amount": "0"},
            {"id": 4, "amount": "-5"},
        ], 4))
    body = await _average()
    assert body["complete"] is True
    assert body["snapshot_consistency"] == "not_guaranteed"
    assert (body["upstream_total_count"], body["scanned_count"],
            body["invoices_with_amount"], body["excluded_amount_count"]) == (4, 4, 2, 2)
    assert body["unrounded_total_amount"] == "2.008"
    assert body["total_amount"] == "2.01"
    assert body["average_invoice"] == 1.01
    query = parse_qs(urlparse(str(route.calls[0].request.url)).query)
    filters = json.loads(query["filter"][0])
    assert ("invoice_date", ">=", "2020-01-01 00:00:00") in {
        (f["property"], f["operator"], f["value"]) for f in filters}
    assert ("invoice_date", "<", "2022-01-01 00:00:00") in {
        (f["property"], f["operator"], f["value"]) for f in filters}
    assert ("status", "=", "exec") in {
        (f["property"], f["operator"], f["value"]) for f in filters}


@pytest.mark.asyncio
@respx.mock
async def test_keyset_reconciles_each_page_against_initial_total():
    billing_mock()
    queries = []

    def page(request):
        query = parse_qs(urlparse(str(request.url)).query)
        queries.append(query)
        filters = json.loads(query["filter"][0])
        cursor = next((int(f["value"]) for f in filters if f["property"] == "id"), 0)
        rows = [{"id": i, "amount": "1.00"} for i in range(cursor + 1, min(cursor + 101, 102))]
        return _reply(rows, 101 - cursor)

    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    body = await _average()
    assert len(queries) == 2
    assert all(query["offset"] == ["0"] for query in queries)
    assert body["upstream_total_count"] == body["scanned_count"] == 101
    assert body["invoices_with_amount"] == 101
    assert body["total_amount"] == "101.00"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("total", [None, "2", -1, True, 0])
async def test_ambiguous_first_count_never_returns_average(total):
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=_reply([{"id": 1, "amount": "9.00"}], total))
    with pytest.raises(ToolError, match="totalCount|incomplete|pagination"):
        await _average()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("second_total", [None, 0, "1"])
async def test_ambiguous_following_page_never_returns_average(second_total):
    billing_mock()
    calls = 0

    def page(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            return _reply([{"id": i, "amount": "1"} for i in range(1, 101)], 101)
        return _reply([{"id": 101, "amount": "1"}], second_total)

    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=page)
    with pytest.raises(ToolError, match="totalCount|incomplete|pagination"):
        await _average()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad", [None, "broken-value", "NaN", "Infinity"])
async def test_invalid_mandatory_amount_fails_without_row_value(bad):
    billing_mock()
    row = {"id": 99, "total": "999.00", "sum": "999.00"}
    if bad is not None:
        row["amount"] = bad
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_reply([row], 1))
    with pytest.raises(ToolError) as exc:
        await _average()
    message = str(exc.value)
    assert "amount" in message
    assert "999.00" not in message
    assert "broken-value" not in message
    assert "id=99" not in message


@pytest.mark.asyncio
@respx.mock
async def test_empty_period_is_verified():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_reply([], 0))
    body = await _average()
    assert body["complete"] is True
    assert (body["upstream_total_count"], body["scanned_count"],
            body["excluded_amount_count"], body["invoices_with_amount"]) == (0, 0, 0, 0)
    assert body["unrounded_total_amount"] == "0"


@pytest.mark.asyncio
@respx.mock
async def test_empty_page_without_total_count_is_not_verified():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_reply([], None))
    with pytest.raises(ToolError, match="totalCount"):
        await _average()
