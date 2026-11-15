"""The upstream's empty client marker must not become a found MCP client."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


BASE = "https://testclinic.vetmanager.cloud"


@pytest.mark.asyncio
@respx.mock
async def test_empty_client_marker_is_not_a_successful_client():
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    route = respx.get(f"{BASE}/rest/api/client/999999999").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"totalCount": 0, "client": {"merge_history": []}},
        })
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        with pytest.raises(ToolError, match="Client not found"):
            await mcp.call_tool("get_client_by_id", {"client_id": 999999999})
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_real_client_with_merge_history_stays_visible():
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"totalCount": 1, "client": {"id": 42, "merge_history": []}},
        })
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        result = await mcp.call_tool("get_client_by_id", {"client_id": 42})
    assert result.is_error is False


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("malformed_total", [False, 0.0])
async def test_malformed_empty_client_count_is_an_upstream_error(malformed_total):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/client/999999999").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"totalCount": malformed_total, "client": {"merge_history": []}},
        })
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        with pytest.raises(ToolError, match="Invalid client response"):
            await mcp.call_tool("get_client_by_id", {"client_id": 999999999})


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("client", [None, {}, {"other": []}])
async def test_zero_count_with_unknown_client_shape_is_upstream_error(client):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/client/999999999").mock(
        return_value=httpx.Response(200, json={
            "success": True, "data": {"totalCount": 0, "client": client},
        })
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        with pytest.raises(ToolError, match="Invalid client response"):
            await mcp.call_tool("get_client_by_id", {"client_id": 999999999})
