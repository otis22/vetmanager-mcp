"""Opt-in live smoke for the two affected Report AI tools; safe summary only."""

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
    reason="Requires the .env TEST_DOMAIN/TEST_API_KEY contour",
)
async def test_stage393_live_create_and_read_data(capsys):
    original_request = httpx.AsyncClient.request
    codes = []

    async def capture_status(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/report-ai-job" in str(url):
            codes.append((method, response.status_code))
        return response

    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"],
        is_depersonalized=True,
    )
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture_status):
        created = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество приёмов по месяцам за прошлый месяц без персональных данных."
        })
        job = created.structured_content["data"]["job"]
        try:
            data = await mcp.call_tool("get_report_ai_job_data", {"job_id": job["id"]})
        except ToolError as exc:
            safe_body = {"create_status": job.get("status"), "data_error":
                         "INVALID_TRANSITION" if "INVALID_TRANSITION" in str(exc)
                         else "INTERNAL_ERROR" if "INTERNAL_ERROR" in str(exc)
                         else "other"}
        else:
            safe_body = {"create_status": job.get("status"), "data_status":
                         "rows" if isinstance(data.structured_content.get("data"), dict)
                         else "other"}
    with capsys.disabled():
        print(f"stage393 live HTTP codes={codes} body={safe_body}")
    assert codes and codes[0][0] == "POST" and codes[0][1] in {200, 201}
    assert any(method == "GET" for method, _ in codes)
