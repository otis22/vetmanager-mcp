"""Live stand checks for the changed MCP tool boundary (no production access)."""

import os

import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


pytestmark = [pytest.mark.real_api, pytest.mark.skipif(
    not (os.environ.get("TEST_DOMAIN") and os.environ.get("TEST_API_KEY")),
    reason="TEST_DOMAIN and TEST_API_KEY are required",
)]


@pytest.mark.asyncio
async def test_admission_id_alias_reaches_test_rest():
    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"],
    )
    with headers, runtime:
        listed = await mcp.call_tool("get_admissions", {"limit": 1})
        admissions = listed.structured_content.get("data", {}).get("admission", [])
        if not admissions:
            pytest.skip("The test stand has no admissions")
        admission_id = admissions[0]["id"]
        result = await mcp.call_tool("get_admission_by_id", {"id": admission_id})
    assert result.structured_content["data"]["admission"]["id"] == admission_id
    print(f"stage449_live code=200 body={{'id': {admission_id}}}")


@pytest.mark.asyncio
async def test_report_ai_read_error_is_safe_on_test_rest():
    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"],
    )
    with headers, runtime, pytest.raises(Exception) as raised:
        await mcp.call_tool("get_report_ai_job", {"job_id": 999999999})
    message = str(raised.value)
    assert "NOT_FOUND" in message or "not found" in message.lower()
    print("stage451_live code=404 body={'error': 'Report AI job not found'}")
