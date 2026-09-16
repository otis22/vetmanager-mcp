"""Этап 322.2 — неполная выборка цены всегда отказывает до первого PUT."""

from __future__ import annotations

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "stage322-pages"
API_KEY = "stage322-pages-key"
BASE = "https://stage322-pages.vetmanager.cloud"


def _row(row_id: int) -> dict:
    return {
        "id": row_id, "good_id": 34, "price": "100.00", "clinic_id": 1,
        "unit_sale_id": 0, "status": "active", "price_formation": "fixed",
        "min_price": "0", "max_price": "0", "markup": "0", "coefficient": 1,
    }


async def _call():
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="stage322-pages-token"
    )
    with headers_patch, runtime_patch:
        return await mcp.call_tool("update_good_sale_price", {
            "sale_param_id": 38, "change_percent": 5, "scope": "good", "confirm": True,
        })


def _base(handler):
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=httpx.Response(200, json={"data": {"goodSaleParam": _row(38)}})
    )
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": {"id": 34, "group_id": 72}}})
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(side_effect=handler)
    return respx.put(url__regex=rf"{BASE}/rest/api/goodSaleParam/.*").mock(
        return_value=httpx.Response(200)
    )


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad_total", [None, "101", 101.0, True, -1])
async def test_missing_or_non_integer_total_count_refuses_before_put(bad_total) -> None:
    def handler(_request):
        data = {"goodSaleParam": [_row(38)]}
        if bad_total is not None:
            data["totalCount"] = bad_total
        return httpx.Response(200, json={"data": data})

    put = _base(handler)

    with pytest.raises(Exception) as exc_info:
        await _call()

    assert "totalCount" in str(exc_info.value)
    assert put.call_count == 0

@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("second_rows,second_total", [([], 101), ([_row(101)], 102)])
async def test_early_end_or_changed_total_refuses_before_put(second_rows, second_total) -> None:
    def handler(request):
        offset = int(request.url.params["offset"])
        rows = [_row(i) for i in range(1, 101)] if offset == 0 else second_rows
        total = 101 if offset == 0 else second_total
        return httpx.Response(200, json={"data": {"goodSaleParam": rows, "totalCount": total}})

    put = _base(handler)

    with pytest.raises(Exception):
        await _call()

    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("case", ["oversized", "duplicate", "overshoot"])
async def test_observable_page_inconsistency_refuses_before_put(case: str) -> None:
    def handler(request):
        offset = int(request.url.params["offset"])
        if case == "oversized":
            rows, total = [_row(i) for i in range(1, 102)], 101
        elif offset == 0:
            rows, total = [_row(i) for i in range(1, 101)], 150
        elif case == "duplicate":
            rows, total = [_row(100)] + [_row(i) for i in range(101, 150)], 150
        else:
            rows, total = [_row(i) for i in range(101, 161)], 150
        return httpx.Response(200, json={"data": {"goodSaleParam": rows, "totalCount": total}})

    put = _base(handler)

    with pytest.raises(Exception):
        await _call()

    assert put.call_count == 0
