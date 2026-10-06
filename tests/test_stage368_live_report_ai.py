"""Read-only devtr6 probe: record only safe aggregate response fields."""

import os

import pytest

from fastmcp.exceptions import ToolError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("TEST_DOMAIN") != "devtr6" or not os.environ.get("TEST_API_KEY"),
    reason="Stage 368 live probe is restricted to the devtr6 test contour",
)
async def test_live_report_ai_job_data_safe_projection() -> None:
    for job_id in (2, 4):
        headers, runtime = patch_runtime_credentials(
            os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"],
            is_depersonalized=True,
        )
        with headers, runtime:
            try:
                result = await mcp.call_tool("get_report_ai_job_data", {"job_id": job_id})
            except ToolError as exc:
                if any(code in str(exc) for code in ("HTTP 404", "NOT_FOUND", "INVALID_TRANSITION", "Resource not found")):
                    continue
                raise
        assert not result.is_error
        payload = result.structured_content
        data = payload.get("data", {})
        if not isinstance(data.get("rows"), list):
            continue
        safe_body = {
            "success": payload.get("success"),
            "data": {"rows_count": len(data["rows"]), "total": data.get("total"),
                     "limited": data.get("limited")},
        }
        assert safe_body["success"] is True
        assert isinstance(safe_body["data"]["total"], int)
        print(f"stage368_live_mcp_code=success body={safe_body}")
        return
    pytest.skip("No saved Report AI fixture on devtr6")
