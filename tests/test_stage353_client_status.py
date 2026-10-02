"""Guard the client status contract at the public MCP boundary."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.test_e2e_mock_crud import BASE, bearer_runtime_patch, billing_mock


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", ["INACTIVE", "DELETED", "disabled", " ACTIVE "])
async def test_update_rejects_unsafe_status_before_http(status):
    billing_mock()
    route = respx.route(host__regex=r".*").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(ToolError) as error:
        await mcp.call_tool("update_client", {"client_id": 42, "status": status})
    message = str(error.value)
    assert "ACTIVE" in message and "DISABLED" in message and "DELETED" in message
    assert "inactive client" in message and "deleted client" in message
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_clients_rejects_unknown_status_before_http():
    billing_mock()
    route = respx.route(host__regex=r".*").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(ToolError) as error:
        await mcp.call_tool("get_clients", {"status": "INACTIVE"})
    assert "DISABLED" in str(error.value)
    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_disabled_is_sent_by_both_tools():
    billing_mock()
    update = respx.put(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"status": "DISABLED"}})
    )
    listing = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"client": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("update_client", {"client_id": 42, "status": "DISABLED"})
        await mcp.call_tool("get_clients", {"status": "DISABLED"})
    assert update.call_count == listing.call_count == 1
    assert b'DISABLED' in update.calls.last.request.content
    assert 'DISABLED' in str(listing.calls.last.request.url)


@pytest.mark.asyncio
async def test_exported_client_descriptions_have_real_statuses():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    for name in ("get_clients", "update_client"):
        description = tools[name].description
        assert "ACTIVE" in description and "DISABLED" in description
        assert "DELETED" in description and "INACTIVE" not in description
        assert "inactive client" in description and "deleted client" in description
