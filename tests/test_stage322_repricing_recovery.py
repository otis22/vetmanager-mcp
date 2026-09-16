"""Этап 322.1 — частичная переоценка возвращает безопасный recovery report."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "stage322"
API_KEY = "stage322-mock-key"
BASE = "https://stage322.vetmanager.cloud"

ROWS = [
    {
        "id": row_id, "good_id": 34, "price": price, "clinic_id": clinic_id,
        "unit_sale_id": 0, "status": "active", "price_formation": "fixed",
        "min_price": "0", "max_price": "0", "markup": "0", "coefficient": 1,
    }
    for row_id, price, clinic_id in (
        (38, "100.0000000000", 1),
        (39, "200.0000000000", 2),
        (41, "300.0000000000", 3),
    )
]


async def _call(**kwargs):
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="stage322-token"
    )
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_good_sale_price", kwargs)
    return result.structured_content if hasattr(result, "structured_content") else result


def _base_mocks(rows=None):
    selected = [dict(row) for row in (rows or ROWS)]
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    initial = dict(selected[0])
    respx.get(f"{BASE}/rest/api/goodSaleParam/{initial['id']}").mock(
        return_value=httpx.Response(200, json={"data": {"goodSaleParam": initial}})
    )
    respx.get(f"{BASE}/rest/api/good/34").mock(
        return_value=httpx.Response(200, json={"data": {"good": {
            "id": 34, "title": "Stage 322", "group_id": 72,
        }}})
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": {
            "goodSaleParam": selected, "totalCount": len(selected),
        }})
    )
    return selected


def _verification(row: dict, price: str) -> httpx.Response:
    return httpx.Response(200, json={"data": {"goodSaleParam": dict(row, price=price)}})


@pytest.mark.asyncio
@respx.mock
async def test_second_put_failure_reports_updated_failed_and_untouched() -> None:
    rows = _base_mocks()
    respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(return_value=_verification(rows[0], "110.00"))
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        side_effect=[_verification(rows[0], rows[0]["price"]), _verification(rows[0], "110.0000000000")]
    )
    respx.put(f"{BASE}/rest/api/goodSaleParam/39").mock(
        return_value=httpx.Response(404, json={"success": False, "message": "Record not found"})
    )

    answer = await _call(sale_param_id=38, change_percent=10, scope="good", confirm=True)

    assert answer["status"] == "partial"
    assert answer["complete"] is False and answer["applied"] is False
    assert answer["partially_applied"] is True and answer["acknowledged_writes"] == 1
    assert answer["updated_rows"] == 1
    assert answer["updated"] == [{
        "sale_param_id": 38, "clinic_id": 1, "before": "100.0000000000",
        "target": "110.00", "after": "110.0000000000",
    }]
    assert answer["failed"]["sale_param_id"] == 39
    assert answer["failed"]["phase"] == "put"
    assert answer["failed"]["write_state"] == "not_written"
    assert answer["failed"]["reason"]["code"] == "http_404"
    assert [row["sale_param_id"] for row in answer["untouched"]] == [41]
    assert answer["resume_calls"] == [{
        "sale_param_id": 41, "scope": "row", "new_price": "330.00",
        "expected_price": "300.0000000000", "confirm": True,
    }]
    assert answer["retry_policy"]["repeat_same_percentage_call"] is False
    assert answer["before"] == "100.0000000000" and answer["after"] == "110.0000000000"


@pytest.mark.asyncio
@respx.mock
async def test_first_put_timeout_is_unknown_and_does_not_leak_raw_detail() -> None:
    _base_mocks()
    secret_detail = "https://private.example/path?api_key=do-not-echo"

    with patch("tools.warehouse.crud_update", side_effect=TimeoutError(secret_detail)):
        answer = await _call(
            sale_param_id=38, change_percent=10, scope="good", confirm=True
        )

    assert answer["status"] == "failed"
    assert answer["applied"] is False and answer["partially_applied"] is False
    assert answer["updated"] == [] and answer["updated_rows"] == 0
    assert answer["before"] is None and answer["after"] is None
    assert answer["failed"]["write_acknowledged"] is False
    assert answer["failed"]["write_state"] == "unknown"
    assert answer["failed"]["reason"]["code"] == "timeout"
    assert secret_detail not in json.dumps(answer)
    assert [row["sale_param_id"] for row in answer["untouched"]] == [39, 41]
    assert {call["sale_param_id"] for call in answer["resume_calls"]} == {39, 41}


@pytest.mark.asyncio
@respx.mock
async def test_non_404_put_rejection_keeps_write_state_unknown() -> None:
    _base_mocks()
    respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=httpx.Response(409, json={"success": False, "message": "conflict"})
    )

    answer = await _call(sale_param_id=38, change_percent=10, scope="good", confirm=True)

    assert answer["status"] == "failed"
    assert answer["failed"]["reason"]["code"] == "http_409"
    assert answer["failed"]["write_acknowledged"] is False
    assert answer["failed"]["write_state"] == "unknown"


@pytest.mark.asyncio
@respx.mock
async def test_verification_mismatch_is_not_reported_as_updated() -> None:
    rows = _base_mocks()
    respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(return_value=_verification(rows[0], "110.00"))
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        side_effect=[_verification(rows[0], rows[0]["price"]), _verification(rows[0], "109.99")]
    )

    answer = await _call(sale_param_id=38, change_percent=10, scope="good", confirm=True)

    assert answer["status"] == "partial" and answer["applied"] is False
    assert answer["updated"] == []
    assert answer["failed"]["phase"] == "verify"
    assert answer["failed"]["write_acknowledged"] is True
    assert answer["failed"]["write_state"] == "unknown"
    assert answer["failed"]["reason"]["code"] == "verification_mismatch"
    assert {call["sale_param_id"] for call in answer["resume_calls"]} == {39, 41}


@pytest.mark.asyncio
@respx.mock
async def test_percentage_target_is_rounded_before_put_and_verification() -> None:
    row = dict(ROWS[0], price="1234.5600000000")
    _base_mocks([row])
    put = respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=_verification(row, "1320.9800000000")
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        side_effect=[_verification(row, row["price"]), _verification(row, "1320.9800000000")]
    )

    answer = await _call(sale_param_id=38, change_percent=7, scope="row", confirm=True)

    assert json.loads(put.calls[0].request.content)["price"] == "1320.98"
    assert answer["complete"] is True and answer["status"] == "completed"
    assert answer["updated"][0]["target"] == "1320.98"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "kwargs",
    [
        {"sale_param_id": 38, "new_price": 100, "expected_price": "100"},
        {"sale_param_id": 38, "new_price": 100, "scope": "good", "confirm": True,
         "expected_price": "100"},
        {"sale_param_id": 38, "change_percent": 5, "scope": "group", "confirm": True,
         "expected_price": "100"},
    ],
)
async def test_expected_price_rejects_unsupported_combinations_before_put(kwargs) -> None:
    _base_mocks()
    read = respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=_verification(ROWS[0], ROWS[0]["price"])
    )
    put = respx.put(url__regex=rf"{BASE}/rest/api/goodSaleParam/.*").mock(
        return_value=httpx.Response(500)
    )

    with pytest.raises(Exception):
        await _call(**kwargs)

    assert read.call_count == 0
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_expected_price_mismatch_refuses_before_put() -> None:
    _base_mocks()
    put = respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(return_value=httpx.Response(500))

    with pytest.raises(Exception) as exc_info:
        await _call(
            sale_param_id=38, new_price=110, expected_price="99.00",
            scope="row", confirm=True,
        )

    assert "expected_price" in str(exc_info.value)
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_expected_price_equal_with_different_scale_allows_noop_write() -> None:
    rows = _base_mocks()
    put = respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=_verification(rows[0], "100.0000000000")
    )
    respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(
        side_effect=[_verification(rows[0], rows[0]["price"]), _verification(rows[0], "100.0000000000")]
    )

    answer = await _call(
        sale_param_id=38, new_price=100, expected_price="100.00",
        scope="row", confirm=True,
    )

    assert put.call_count == 1
    assert answer["complete"] is True and answer["applied"] is True
