"""Live negative client witness on the isolated .env API-key contour."""

import os
from unittest.mock import patch

import httpx
import pytest
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(
    not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
    reason="TEST_DOMAIN and TEST_API_KEY are required",
)
async def test_missing_client_marker_is_not_returned_as_client():
    seen = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if method == "GET" and str(url).endswith("/rest/api/client/999999999"):
            data = response.json().get("data", {})
            seen.append((response.status_code, data.get("totalCount"), data.get("client")))
        return response

    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"],
        is_depersonalized=False,
    )
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        with pytest.raises(ToolError, match="Client not found"):
            await mcp.call_tool("get_client_by_id", {"client_id": 999999999})

    assert len(seen) == 1
    code, total, client = seen[0]
    assert code == 200 and type(total) is int and total == 0
    shape = (
        "empty_list" if client == [] else
        "empty_merge_history" if client == {"merge_history": []} else
        "unexpected"
    )
    assert shape != "unexpected", "Unexpected client shape"
    print("STAGE459_LIVE upstream_code=200 body=" + str({
        "success": True, "totalCount": total,
        "client_shape": shape,
        "mcp_error": "Client not found",
    }))
