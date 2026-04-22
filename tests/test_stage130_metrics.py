"""Stage 130 observability counters for token presets and sanitizer failures."""

from unittest.mock import patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import depersonalization
from server import mcp
from service_metrics import reset_service_metrics, snapshot_service_metrics
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


@pytest.mark.asyncio
@respx.mock
async def test_depersonalization_fail_closed_increments_sanitizer_metric():
    reset_service_metrics()
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42, "firstName": "Anna"}})
    )

    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
        is_depersonalized=True,
    )
    with (
        headers_patch,
        runtime_patch,
        patch.object(depersonalization, "sanitize_tool_result", side_effect=RuntimeError("boom")),
    ):
        with pytest.raises(ToolError, match="Depersonalization failed."):
            await mcp.call_tool("get_client_by_id", {"client_id": 42})

    snapshot = snapshot_service_metrics()
    assert snapshot["sanitizer_failures_total"] == 1
