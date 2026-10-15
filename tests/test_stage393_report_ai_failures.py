"""Regression guards for KI 58/59/60 at the public Report AI boundary."""

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from agent_feedback_service import build_error_fingerprint_hash, build_incident_from_exception
from exceptions import VetmanagerError
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from token_scopes import SCOPE_ANALYTICS_READ
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS
import tools.report_ai as report_ai
import tools
from prompts import get_report_ai_prompt_helper_text


RAW_COMBINATION_ERROR = (
    "SQLSTATE[42000]: Syntax error or access violation: 1064 "
    "You have an error in your SQL syntax near `good_tag` SELECT secret"
)


def _failed(message: str, *, code: str = "PREVIEW_FAILED", status: str = "failed") -> dict:
    return {"data": {"job": {"status": status, "error_code": code,
                              "error_message_safe": message}}}


def test_combination_sql_failure_gets_non_retry_workaround_without_sql():
    job = report_ai._annotate_report_ai_workarounds(_failed(RAW_COMBINATION_ERROR))["data"]["job"]
    workaround = job["mcp_workaround"]
    assert workaround["safe_to_retry"] is False
    assert "get_good_combination" in str(workaround)
    assert "calculate_good_combination_price" in str(workaround)
    assert "SELECT secret" not in str(job)
    assert "SQLSTATE" not in str(job)


@pytest.mark.parametrize("message,code,status", [
    ("SQLSTATE[42000]: syntax error near good_tag", "OTHER", "failed"),
    ("SQLSTATE[42000]: syntax error near good_tag", "PREVIEW_FAILED", "queued"),
    ("SQLSTATE[42000]: syntax error near my_good_tag_extra", "PREVIEW_FAILED", "failed"),
    ("SQLSTATE[42000]: syntax error near good.id", "PREVIEW_FAILED", "failed"),
    ("good_tag without SQLSTATE", "PREVIEW_FAILED", "failed"),
])
def test_combination_classifier_requires_all_markers(message, code, status):
    job = report_ai._annotate_report_ai_workarounds(_failed(message, code=code, status=status))["data"]["job"]
    assert job.get("mcp_workaround", {}).get("safe_to_retry") is not False
    assert "SQLSTATE" not in str(job)


def test_combination_failure_wins_over_legacy_good_id():
    job = report_ai._annotate_report_ai_workarounds(
        _failed(RAW_COMBINATION_ERROR + " and good.id")
    )["data"]["job"]
    assert job["mcp_workaround"]["safe_to_retry"] is False


def test_read_500_classifier_preserves_ki_incident_and_fingerprint(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage393-test-pepper")
    original = VetmanagerError("Внутренняя ошибка", status_code=500, error_code="INTERNAL_ERROR")
    before = build_incident_from_exception("get_report_ai_job_data", original)
    report_ai._classify_report_ai_data_failure(original)
    after = build_incident_from_exception("get_report_ai_job_data", original)
    assert after == before
    assert build_error_fingerprint_hash(after) == build_error_fingerprint_hash(before)
    assert "safe_to_retry=true" in str(original)
    assert "get_report_ai_job" in str(original)


@pytest.mark.parametrize("status,code", [(502, "INTERNAL_ERROR"), (500, "OTHER"),
                                         (409, "INVALID_TRANSITION")])
def test_read_failure_classifier_is_narrow(status, code):
    original = VetmanagerError("original", status_code=status, error_code=code)
    report_ai._classify_report_ai_data_failure(original)
    assert str(original) == "original"
    assert not hasattr(original, "feedback_safe_excerpt")


@pytest.mark.asyncio
@respx.mock
async def test_read_500_registered_tool_gives_safe_retry_advice(monkeypatch):
    billing_mock()
    source_seen = []

    async def capture_source(tool_name, credentials, exc, *, incident_source=None, **kwargs):
        source_seen.append(build_incident_from_exception(tool_name, incident_source))
        return exc

    monkeypatch.setattr(tools, "_with_known_issue_hint", capture_source)
    route = respx.get(f"{BASE}/rest/api/report-ai-job/22/data").mock(
        return_value=httpx.Response(500, json={
            "success": False, "message": "Внутренняя ошибка",
            "data": {"error_code": "INTERNAL_ERROR"},
        })
    )
    headers_patch, runtime_patch = bearer_runtime_patch(scopes=(SCOPE_ANALYTICS_READ,))
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as caught:
            await mcp.call_tool("get_report_ai_job_data", {"job_id": 22})
    assert route.call_count == 1
    assert "safe_to_retry=true" in str(caught.value)
    assert "save" in str(caught.value).lower()
    assert "INTERNAL_ERROR" in str(caught.value)
    assert len(source_seen) == 1
    assert source_seen[0].http_status == 500
    assert source_seen[0].error_code == "INTERNAL_ERROR"
    assert "Внутренняя ошибка" in source_seen[0].error_excerpt
    assert "safe_to_retry" not in source_seen[0].error_excerpt


def test_stock_warning_reaches_description_and_prompt_helper():
    for text in (SPECIAL_TOOL_DESCRIPTIONS["create_report_ai_job"],
                 get_report_ai_prompt_helper_text()):
        assert "Текущий остаток на складе" in text
        assert "get_good_stock_balance" in text
        assert "clinic_id" in text
