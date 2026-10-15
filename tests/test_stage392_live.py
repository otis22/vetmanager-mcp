"""Opt-in devtr6 live check; prints only a safe response summary."""

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
    reason="Requires the devtr6 .env test contour",
)
async def test_stage392_live_create_report_job_echo(capsys):
    intent = "Количество приёмов по месяцам. Без ФИО, телефонов и других персональных данных."
    original_request = httpx.AsyncClient.request
    codes = []

    async def capture_status(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if method == "POST" and "/rest/api/report-ai-job" in str(url):
            codes.append(response.status_code)
        return response

    headers, runtime = patch_runtime_credentials(
        "devtr6", os.environ["TEST_API_KEY"], is_depersonalized=True,
    )
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture_status):
        created = await mcp.call_tool("create_report_ai_job", {"intent_text": intent})
    job = created.structured_content["data"]["job"]
    echo = job.get("intent_text", "")
    safe_body = {
        "status": job.get("status"),
        "echo_has_phrase": "Без ФИО, телефонов и других персональных данных." in echo,
        "echo_has_broken_token": "[redacted-name]О" in echo,
        "echo_has_privacy_requirement": "Важно: не включай" in echo,
    }
    with capsys.disabled():
        print(f"stage392 live HTTP codes={codes} body={safe_body}")
    assert codes and codes[0] in {200, 201}
    assert safe_body["echo_has_phrase"]
    assert not safe_body["echo_has_broken_token"]
    assert safe_body["echo_has_privacy_requirement"]
