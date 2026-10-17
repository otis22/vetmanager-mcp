"""Stage 417: agents score report usefulness, not intentional PII placeholders."""

import pytest

from prompts import get_report_ai_prompt_helper_text
from server import mcp


REPORT_TOOLS = (
    "create_report_ai_job",
    "get_report_ai_job",
    "get_report_ai_job_data",
    "rate_report_ai_job",
)


def _assert_privacy_guidance(text: str) -> None:
    lowered = text.lower()
    for meaning in (
        "even with a personal-data token",
        "names and phone numbers",
        "placeholders",
        "by design",
        "does not guarantee redaction of every report",
        "do not lower the score solely",
        "when the task is solved",
        "contact task",
    ):
        assert meaning in lowered


@pytest.mark.asyncio
@pytest.mark.parametrize("name", REPORT_TOOLS)
async def test_report_tool_description_explains_intentional_privacy(name):
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    description = tools[name].description
    if name == "rate_report_ai_job":
        for meaning in (
            "даже при токене с ПД",
            "ФИО",
            "телефоны",
            "плейсхолдерами",
            "не гарантия очистки каждого отчёта",
            "не снижайте оценку только",
            "если задача решена",
            "контактной задачи",
        ):
            assert meaning in description
    else:
        _assert_privacy_guidance(description)


def _assert_helper_privacy_guidance(text: str) -> None:
    text = " ".join(text.split())
    for meaning in (
        "даже при токене с ПД",
        "ФИО",
        "телефоны",
        "плейсхолдерами",
        "не гарантия очистки каждого отчёта",
        "не снижайте оценку только",
        "если задача решена",
        "контактной задачи",
    ):
        assert meaning in text


def test_prompt_helper_explains_intentional_privacy():
    text = get_report_ai_prompt_helper_text()
    _assert_helper_privacy_guidance(text)
    with pytest.raises(AssertionError):
        _assert_helper_privacy_guidance(text.replace("не гарантия очистки каждого отчёта", "гарантия очистки каждого отчёта"))
    with pytest.raises(AssertionError):
        _assert_helper_privacy_guidance(text.replace("если\nзадача решена", "всегда"))


def _assert_rating_contract(rate: str, helper: str) -> None:
    for meaning in (
        "1 = отчёт даже не построился",
        "2 и выше — отчёт построился",
        "5–6 = решил частично",
        "10 = задача решена полностью",
        "intent_text и score обязательны",
        "comment необязателен",
    ):
        assert meaning in rate
    for meaning in (
        "1 = отчёт даже не построился",
        "2 и выше — отчёт построился",
        "5–6 = решил частично",
        "10 = задача решена полностью",
        "rate_report_ai_job(job_id, score, intent_text)",
        "`score` и `intent_text`",
    ):
        assert meaning in helper


@pytest.mark.asyncio
async def test_rating_scale_and_final_step_keep_their_meaning():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    rate = tools["rate_report_ai_job"].description
    helper = get_report_ai_prompt_helper_text()
    _assert_rating_contract(rate, helper)
    # Break each protected surface in memory to prove this guard goes red.
    with pytest.raises(AssertionError):
        _assert_rating_contract(rate.replace("5–6 = решил частично", "5–6 = решил полностью"), helper)
    with pytest.raises(AssertionError):
        _assert_rating_contract(rate, helper.replace("rate_report_ai_job(job_id, score, intent_text)", "rate_report_ai_job(job_id, score)"))


@pytest.mark.asyncio
async def test_tool_privacy_guard_rejects_lost_qualifiers():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    description = tools["get_report_ai_job_data"].description
    with pytest.raises(AssertionError):
        _assert_privacy_guidance(description.replace(
            "does not guarantee redaction of every report", "guarantees redaction of every report"))
    with pytest.raises(AssertionError):
        _assert_privacy_guidance(description.replace("when the task is solved", "for every task"))
