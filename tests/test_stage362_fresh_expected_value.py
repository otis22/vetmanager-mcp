"""Stage 362: pre-write comparisons bypass stale cache and refresh it."""

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient


BASE = "https://stage362.vetmanager.cloud"
ROW = {"id": 38, "good_id": 34, "clinic_id": 1, "unit_sale_id": 4,
       "status": "active", "price": "100.0000000000", "price_formation": "fixed"}


async def call(name, **args):
    headers, runtime = patch_runtime_credentials("stage362", "mock-key")
    with headers, runtime:
        result = await mcp.call_tool(name, args)
    return result.structured_content


def setup():
    respx.get("https://billing-api.vetmanager.cloud/host/stage362").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}}))
    state = {"price": ROW["price"], "status": ROW["status"], "fail": False}

    def read(_request):
        if state["fail"]:
            return httpx.Response(404, json={"success": False})
        return httpx.Response(200, json={"data": {"goodSaleParam": dict(
            ROW, price=state["price"], status=state["status"])}})

    get = respx.get(f"{BASE}/rest/api/goodSaleParam/38").mock(side_effect=read)
    respx.get(f"{BASE}/rest/api/good/34").mock(return_value=httpx.Response(
        200, json={"data": {"good": {"id": 34, "title": "Test", "group_id": 0}}}))
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(return_value=httpx.Response(
        200, json={"data": {"goodSaleParam": [ROW], "totalCount": 1}}))
    put = respx.put(f"{BASE}/rest/api/goodSaleParam/38").mock(
        return_value=httpx.Response(500))
    return state, get, put


@pytest.mark.asyncio
@respx.mock
async def test_price_guard_uses_fresh_value_and_refreshes_normal_read():
    state, get, put = setup()
    first = await call("get_good_sale_param_by_id", param_id=38)
    assert first["data"]["goodSaleParam"]["price"] == ROW["price"]
    state["price"] = "220.0000000000"
    cached = await call("get_good_sale_param_by_id", param_id=38)
    assert cached["data"]["goodSaleParam"]["price"] == ROW["price"]
    assert get.call_count == 1

    with pytest.raises(Exception) as error:
        await call("update_good_sale_price", sale_param_id=38, scope="row",
                   new_price=110, expected_price="100.00", confirm=True)
    assert "expected_price" in str(error.value)
    assert "220.0000000000" in str(error.value)
    assert put.call_count == 0
    assert get.call_count == 2

    refreshed = await call("get_good_sale_param_by_id", param_id=38)
    assert refreshed["data"]["goodSaleParam"]["price"] == state["price"]
    assert get.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_failed_fresh_price_check_does_not_fall_back_to_cache_or_write():
    state, get, put = setup()
    await call("get_good_sale_param_by_id", param_id=38)
    state["fail"] = True
    with pytest.raises(Exception):
        await call("update_good_sale_price", sale_param_id=38, scope="row",
                   new_price=110, expected_price="100", confirm=True)
    assert get.call_count == 2
    assert put.call_count == 0
    cached = await call("get_good_sale_param_by_id", param_id=38)
    assert cached["data"]["goodSaleParam"]["price"] == ROW["price"]
    assert get.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_invalid_fresh_price_refuses_before_write():
    state, get, put = setup()
    await call("get_good_sale_param_by_id", param_id=38)
    state["price"] = "not-a-number"
    with pytest.raises(Exception, match="unusable price"):
        await call("update_good_sale_price", sale_param_id=38, scope="row",
                   new_price=110, expected_price="100", confirm=True)
    assert get.call_count == 2
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_status_confirmation_ignores_a_warmed_stale_row():
    state, get, put = setup()
    respx.get(f"{BASE}/rest/api/clinics/1").mock(return_value=httpx.Response(
        200, json={"data": {"clinics": {"id": 1, "title": "Test"}}}))
    preview = await call("set_good_sale_param_status", sale_param_id=38,
                         clinic_id=1, target_status="disabled")
    await call("get_good_sale_param_by_id", param_id=38)
    state["status"] = "disabled"
    with pytest.raises(Exception, match="changed or confirmation does not match"):
        await call("set_good_sale_param_status", sale_param_id=38, clinic_id=1,
                   target_status="disabled", confirm=True,
                   confirmation=preview["confirmation"])
    assert get.call_count == 2
    assert put.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_fresh_get_keeps_uncached_endpoint_exclusion():
    respx.get("https://billing-api.vetmanager.cloud/host/stage362").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}}))
    route = respx.get(f"{BASE}/rest/api/report/startreport").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}}))
    headers, runtime = patch_runtime_credentials("stage362", "mock-key")
    with headers, runtime:
        client = VetmanagerClient()
        await client.get("/rest/api/report/startreport", fresh=True)
        await client.get("/rest/api/report/startreport")
    assert route.call_count == 2
