"""Stage 437: the save result must ask for a rating without changing its contract."""

import httpx
import pytest
import respx

from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock


@pytest.mark.asyncio
@pytest.mark.parametrize("idempotent", [False, True])
@respx.mock
async def test_save_response_prompts_one_call_rating_after_full_data_review(idempotent):
    billing_mock()
    upstream_data = {"report_id": 437, "is_idempotent": idempotent}
    respx.post(f"{BASE}/rest/api/report-ai-job/437/save").mock(
        return_value=httpx.Response(200, json={
            "success": True, "message": "", "data": upstream_data,
        }))
    headers, runtime = bearer_runtime_patch(is_depersonalized=True)
    with headers, runtime:
        result = (await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 437, "title": "MCP количество приёмов за октябрь 2026",
        })).structured_content

    assert result["success"] is True
    assert result["message"] == ""
    data = result["data"]
    assert data["report_id"] == upstream_data["report_id"]
    assert data["is_idempotent"] is idempotent
    assert data["next_action"]["call"] == {
        "tool": "get_report_ai_job_data", "arguments": {"job_id": 437}}
    prompt = data["mcp_rating_prompt"]
    for phrase in (
        "сейчас", "get_report_ai_job_data", "rate_report_ai_job",
        "1-10", "1 - отчёт не построился", "10 - задача решена полностью",
        "одним вызовом", "Комментарий необязателен", "intent_text",
        "limited=true", "экспорт", "уже оценено",
    ):
        assert phrase.lower() in prompt.lower()
    assert prompt.index("get_report_ai_job_data") < prompt.index("rate_report_ai_job")
    assert "MCP количество приёмов" not in prompt


@pytest.mark.asyncio
@respx.mock
async def test_unconfirmed_save_outcome_has_no_rating_prompt():
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/437/save").mock(
        return_value=httpx.Response(200, json={
            "success": True, "data": {"job": {"id": 437, "status": "queued"}},
        }))
    headers, runtime = bearer_runtime_patch(is_depersonalized=True)
    with headers, runtime:
        result = (await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 437, "title": "MCP количество приёмов за октябрь 2026",
        })).structured_content
    job = result["data"]["job"]
    assert job["next_action"]["type"] == "verify_save_outcome"
    assert "mcp_rating_prompt" not in result["data"]
