"""Opt-in read-only devtr6 probe of Report AI outcome log IDs."""

import logging
import os

import pytest
from fastmcp.exceptions import ToolError

from exceptions import VetmanagerError
from server import mcp
from tests.runtime_factories import make_client_with_resolved_runtime, patch_runtime_credentials


pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
async def test_devtr6_missing_report_ai_job_logs_numeric_ids(caplog):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    job_id = 2147483647
    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"],
                                                 os.environ["TEST_API_KEY"], account_id=1)
    client = make_client_with_resolved_runtime(os.environ["TEST_DOMAIN"],
                                               os.environ["TEST_API_KEY"], account_id=1)
    with pytest.raises(VetmanagerError) as upstream:
        await client.get(f"/rest/api/report-ai-job/{job_id}", retry=False)
    assert upstream.value.status_code == 404
    with caplog.at_level(logging.INFO), headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("get_report_ai_job", {"job_id": job_id})
    records = [record for record in caplog.records if record.msg == "report_ai_outcome_code"]
    assert len(records) == 1
    event = records[0]
    assert type(event.account_id) is type(event.job_id) is int
    assert (event.account_id, event.job_id) == (1, job_id)
    assert event.code in {"NOT_FOUND", "no_code_http_4xx"}
    assert "Report AI request failed" in str(error.value)
    print(f"LIVE http={upstream.value.status_code} body={str(error.value)!r} "
          f"log=report_ai_outcome_code account_id={event.account_id} job_id={event.job_id} code={event.code}")
