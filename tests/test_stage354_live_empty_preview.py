"""Opt-in devtr6 smoke for stage 354; prints only safe response fields."""

import asyncio
import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("TEST_DOMAIN") != "devtr6" or not os.environ.get("TEST_API_KEY"),
    reason="Requires devtr6 test API credentials",
)
async def test_live_zero_preview_guidance():
    original_request = httpx.AsyncClient.request
    http_codes = []

    async def capture_report_job_status(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/report-ai-job" in str(url):
            http_codes.append((method, response.status_code))
        return response

    headers, runtime = patch_runtime_credentials(
        "devtr6", os.environ["TEST_API_KEY"],
    )
    intent = (
        "Покажи список медицинских карт за 1 января 1900 года: "
        "ID карты, дату и ID клиники. Дата строго 01.01.1900."
    )
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture_report_job_status):
        created = await mcp.call_tool("create_report_ai_job", {"intent_text": intent})
        job = created.structured_content["data"]["job"]
        job_id = job["id"]
        for _ in range(40):
            result = await mcp.call_tool("get_report_ai_job", {"job_id": job_id})
            job = result.structured_content["data"]["job"]
            if job.get("status") in {"ready_to_save", "failed", "rejected"}:
                break
            await asyncio.sleep(15)
    safe_body = {
        "status": job.get("status"),
        "preview_summary": job.get("preview_summary"),
        "guidance_code": (job.get("mcp_empty_preview_guidance") or {}).get("code"),
    }
    print(f"stage354 devtr6 HTTP codes={http_codes} body={safe_body}")
    assert ("POST", 200) in http_codes or ("POST", 201) in http_codes
    assert ("GET", 200) in http_codes
    assert job.get("status") == "ready_to_save"
    assert "Превью: 0 строк" in job.get("preview_summary", "")
    assert safe_body["guidance_code"] == "report_ai_empty_preview"
