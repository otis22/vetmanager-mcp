"""Stage 354: Report AI guidance reaches the MCP caller."""

import httpx
import pytest
import respx

from server import mcp
from tests.test_stage170_report_ai_tools import BASE, billing_mock, bearer_runtime_patch


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("summary,expected", [
    ("Превью: 0 строк, 3 колонок", True),
    ("Превью: 0 строк", True),
    ("Превью: 10 строк, 3 колонки", False),
    ("Превью: 0 строк из 10", False),
    (None, False),
])
async def test_zero_preview_guidance_is_conditional(summary, expected):
    billing_mock()
    original = {"id": 354, "status": "ready_to_save", "preview_summary": summary}
    respx.get(f"{BASE}/rest/api/report-ai-job/354").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": original}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 354})
    job = result.structured_content["data"]["job"]
    assert all(job[k] == v for k, v in original.items())
    guidance = job.get("mcp_empty_preview_guidance")
    assert bool(guidance) is expected
    if expected:
        message = " ".join(guidance["steps"]).lower()
        assert "get_medical_cards_by_date" in message
        assert "до сохранения" in message
        assert "не называйте отчёт рабочим" in message
        assert "согласия человека" in message


@pytest.mark.asyncio
@respx.mock
async def test_zero_preview_guidance_requires_ready_to_save():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/354").mock(return_value=httpx.Response(
        200, json={"data": {"job": {
            "id": 354, "status": "saved", "preview_summary": "Превью: 0 строк, 3 колонки"
        }}}
    ))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        job = (await mcp.call_tool("get_report_ai_job", {"job_id": 354})).structured_content["data"]["job"]
    assert "mcp_empty_preview_guidance" not in job


@pytest.mark.asyncio
@respx.mock
async def test_deduplicated_create_also_guides_zero_preview():
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(return_value=httpx.Response(
        200, json={"data": {"job": {
            "id": 354, "status": "ready_to_save",
            "preview_summary": "Превью: 0 строк, 3 колонки",
            "is_deduplicated": True,
        }}}
    ))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        job = (await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество карт за вчера",
        })).structured_content["data"]["job"]
    assert job["mcp_empty_preview_guidance"]["code"] == "report_ai_empty_preview"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("depersonalized", [True, False, None])
async def test_staff_id_guidance_follows_privacy_mode(depersonalized):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/354").mock(return_value=httpx.Response(
        200, json={"data": {"job": {"id": 354, "status": "ready_to_save",
                                  "preview_summary": "Превью: 2 строк, 3 колонки"}}}
    ))
    headers, runtime = bearer_runtime_patch(is_depersonalized=depersonalized)
    with headers, runtime:
        job = (await mcp.call_tool("get_report_ai_job", {"job_id": 354})).structured_content["data"]["job"]
    guidance = job.get("mcp_personal_data_guidance")
    assert bool(guidance) is (depersonalized is True)
    if depersonalized is True:
        message = " ".join(guidance["steps"]).lower()
        assert "сотрудник" in message
        assert "настройк" in message
        assert "не ошибка конструктора" in message
        assert "не обходите" in message


@pytest.mark.asyncio
async def test_medical_card_html_guidance_is_in_mcp_helper():
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_prompt_helper", {})
    body = result.structured_content["helper_text"]
    assert "HTML" in body
    assert "<div></div>" in body
    assert "пустот" in body.lower()
    assert "разметк" in body.lower()
    assert "короткие признаки" in body
