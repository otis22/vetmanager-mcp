"""Stage 412: explicit clinic context and bounded stock batch."""

import asyncio

import httpx
import pytest
import respx
from fastmcp import Client

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from token_scopes import SCOPE_INVENTORY_READ, required_scope_for_request
from tool_access_registry import TOOL_REQUIRED_SCOPES

BASE = "https://testclinic.vetmanager.cloud"
PATH = "/rest/api/stores/RestOfGoodInWarehouse/"


@pytest.mark.asyncio
async def test_catalog_requires_clinic_for_single_and_batch():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    assert "clinic_id" in tools["get_good_stock_balance"].inputSchema["required"]
    batch = tools["get_goods_stock_balances"]
    assert {"good_ids", "clinic_id"} <= set(batch.inputSchema["required"])
    assert "clinic" in batch.description.lower()


def test_batch_access_and_rest_path_are_mapped():
    assert TOOL_REQUIRED_SCOPES["get_goods_stock_balances"] == (SCOPE_INVENTORY_READ,)
    assert required_scope_for_request("GET", PATH) == SCOPE_INVENTORY_READ


@pytest.mark.asyncio
@respx.mock
async def test_batch_reads_each_good_in_order_from_selected_clinic():
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    seen = []

    def stock(request):
        good_id = int(request.url.params["good_id"])
        seen.append((good_id, request.url.params["clinic_id"]))
        return httpx.Response(200, json={"success": True, "data": {
            "rest_good_in_warehouse": {"quantity": f"{good_id}.000"}}})

    respx.get(f"{BASE}{PATH}").mock(side_effect=stock)
    hp, rp = patch_runtime_credentials("testclinic", "mock-key", bearer_token="mock-token")
    with hp, rp:
        result = await mcp.call_tool("get_goods_stock_balances", {"good_ids": [7, 9], "clinic_id": 2})
    body = result.structured_content
    assert seen == [(7, "2"), (9, "2")]
    assert [row["quantity_str"] for row in body["balances"]] == ["7.000", "9.000"]
    assert body["clinic_id"] == 2


@pytest.mark.asyncio
async def test_missing_clinic_does_not_reach_upstream(monkeypatch):
    reached = False

    async def forbidden(*args, **kwargs):
        nonlocal reached
        reached = True
        raise AssertionError("upstream called without clinic")

    monkeypatch.setattr("vetmanager_client.VetmanagerClient.get", forbidden)
    hp, rp = patch_runtime_credentials("testclinic", "mock-key", bearer_token="mock-token")
    with hp, rp:
        with pytest.raises(Exception, match="clinic_id"):
            await mcp.call_tool("get_goods_stock_balances", {"good_ids": [7, 9]})
        with pytest.raises(Exception, match="clinic_id"):
            await mcp.call_tool("get_good_stock_balance", {"good_id": 7})
    assert not reached


@pytest.mark.asyncio
@pytest.mark.parametrize("stock_value", ["invalid", None])
async def test_batch_rejects_malformed_quantity_and_uses_fresh_reads(monkeypatch, stock_value):
    calls = []

    async def stock(self, path, **kwargs):
        calls.append(kwargs)
        stock = {} if stock_value is None else {"quantity": stock_value}
        return {"success": True, "data": {"rest_good_in_warehouse": stock}}

    monkeypatch.setattr("vetmanager_client.VetmanagerClient.get", stock)
    hp, rp = patch_runtime_credentials("testclinic", "mock-key", bearer_token="mock-token")
    with hp, rp:
        with pytest.raises(Exception, match="no valid stock quantity"):
            await mcp.call_tool("get_goods_stock_balances", {"good_ids": [7], "clinic_id": 2})
    assert len(calls) == 1
    assert calls[0]["fresh"] is True


@pytest.mark.asyncio
async def test_batch_deadline_stops_before_next_good(monkeypatch):
    calls = []

    async def slow_stock(self, path, **kwargs):
        calls.append(kwargs["params"]["good_id"])
        await asyncio.sleep(0.05)
        return {"success": True, "data": {"rest_good_in_warehouse": {"quantity": "1.000"}}}

    monkeypatch.setattr("vetmanager_client.VetmanagerClient.get", slow_stock)
    monkeypatch.setattr("tools.warehouse._STOCK_BATCH_TIMEOUT_SECONDS", 0.01)
    hp, rp = patch_runtime_credentials("testclinic", "mock-key", bearer_token="mock-token")
    with hp, rp:
        with pytest.raises(Exception, match="timed out"):
            await mcp.call_tool("get_goods_stock_balances", {"good_ids": [7, 9], "clinic_id": 2})
    assert calls == [7]


@pytest.mark.asyncio
async def test_batch_rejects_duplicate_or_unbounded_ids_before_rest(monkeypatch):
    calls = []

    async def forbidden(self, path, **kwargs):
        calls.append(kwargs)
        raise AssertionError("invalid batch reached upstream")

    monkeypatch.setattr("vetmanager_client.VetmanagerClient.get", forbidden)
    hp, rp = patch_runtime_credentials("testclinic", "mock-key", bearer_token="mock-token")
    with hp, rp:
        for ids, message in (([7, 7], "unique"), (list(range(1, 22)), "1 to 20"), ([], "1 to 20")):
            with pytest.raises(Exception, match=message):
                await mcp.call_tool("get_goods_stock_balances", {"good_ids": ids, "clinic_id": 2})
    assert calls == []


@pytest.mark.asyncio
async def test_low_stock_prompt_requires_clinic_and_batches():
    prompt = await mcp.get_prompt("low_stock")
    rendered = await prompt.render(arguments={"clinic_id": 2, "threshold": 5})
    body = "\n".join(str(message.content) for message in rendered.messages)
    assert "get_goods_stock_balances" in body
    assert "clinic_id=2" in body
    assert "is_warehouse_account" in body
    assert "offset" in body and "totalCount" in body
    assert "clinic_id=1" not in body
    async with Client(mcp) as client:
        catalogue = {p.name: p for p in await client.list_prompts()}
    args = {arg.name: arg for arg in catalogue["low_stock"].arguments}
    assert args["clinic_id"].required is True
