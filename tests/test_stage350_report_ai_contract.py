"""New Report AI contract: guards must fail against the pre-350 implementation."""

import logging

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import service_metrics
from exceptions import VetmanagerError
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tool_access_registry import TOOL_REQUIRED_SCOPES, PRESET_READ_ONLY, tools_for_preset
from token_scopes import SCOPE_REPORT_AI_WRITE, required_scope_for_request
from tools.report_ai import _annotate_report_ai_data_payload, _annotate_report_ai_workarounds
from tools.report_ai import _safe_export_error
from vetmanager_client import VetmanagerClient


@respx.mock
@pytest.mark.asyncio
async def test_reject_candidate_posts_empty_body_and_then_polls_same_job():
    billing_mock()
    reject = respx.post(f"{BASE}/rest/api/report-ai-job/22/reject").mock(
        return_value=httpx.Response(200, json={"data": {"job": {"id": 22, "status": "needs_confirmation"}}})
    )
    status = respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(
        side_effect=[
            httpx.Response(200, json={"data": {"job": {"id": 22, "status": "needs_confirmation"}}}),
            httpx.Response(200, json={"data": {"job": {"id": 22, "status": "ready_to_save"}}}),
        ]
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 22})
        assert result.structured_content["data"]["job"]["id"] == 22
        first = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
        second = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert reject.call_count == 1
    assert reject.calls.last.request.content == b""
    assert status.call_count == 2
    assert first.structured_content["data"]["job"]["status"] == "needs_confirmation"
    assert second.structured_content["data"]["job"]["status"] == "ready_to_save"


def test_reject_requires_write_scope_and_is_hidden_from_read_only():
    assert TOOL_REQUIRED_SCOPES["reject_report_ai_job_candidate"] == (SCOPE_REPORT_AI_WRITE,)
    assert required_scope_for_request("POST", "/rest/api/report-ai-job/22/reject") == SCOPE_REPORT_AI_WRITE
    assert "reject_report_ai_job_candidate" not in tools_for_preset(PRESET_READ_ONLY)


@respx.mock
@pytest.mark.asyncio
async def test_failed_status_classifies_queue_timeout_and_removes_sql(caplog):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(200, json={
        "data": {"job": {"id": 22, "status": "failed", "error_code": "QUEUE_TIMEOUT",
                         "queue_age_seconds": 3601,
                         "error_message_safe": "SQLSTATE[42S02] SELECT secret FROM clients"}}
    }))
    headers, runtime = bearer_runtime_patch()
    with caplog.at_level(logging.INFO), headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    body = str(result.structured_content)
    assert "SQLSTATE" not in body
    assert "SELECT secret" not in caplog.text
    assert result.structured_content["data"]["job"]["mcp_workaround"]["code"] == "QUEUE_TIMEOUT"
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"]["status|QUEUE_TIMEOUT"] >= 1


@respx.mock
@pytest.mark.asyncio
async def test_start_report_uses_machine_code_and_server_retry_delay():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report/StartReport").mock(return_value=httpx.Response(403, json={
        "message": "SQLSTATE SELECT secret FROM clients",
        "data": {"error_code": "CONSTRUCTOR_BUSY", "retry_after_seconds": 17,
                 "details": {"sql": "SELECT secret FROM clients"}}}
    ))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("start_report_export", {"report_id": 84})
    assert "CONSTRUCTOR_BUSY" in str(error.value)
    assert "17 seconds" in str(error.value)
    assert "SQLSTATE" not in str(error.value)
    assert "SELECT secret" not in repr(error.value)


@respx.mock
@pytest.mark.asyncio
async def test_report_file_not_ready_waits_five_seconds_but_failed_stops():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/reportFile").mock(side_effect=[
        httpx.Response(409, json={"data": {"error_code": "FILE_BUILD_NOT_STARTED", "retry_after_seconds": 5}}),
        httpx.Response(422, json={"data": {"error_code": "FILE_BUILD_FAILED"}}),
    ])
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError, match="5 seconds"):
            await mcp.call_tool("get_report_export_download", {"report_file_id": 324})
        with pytest.raises(ToolError, match="FILE_BUILD_FAILED"):
            await mcp.call_tool("get_report_export_download", {"report_file_id": 324})
    assert route.call_count == 2


def test_limited_is_truthful_at_new_ten_thousand_row_cap():
    data = {"data": {"rows": [{"n": n} for n in range(10000)], "total": 10000, "limited": True}}
    guidance = _annotate_report_ai_data_payload(data)["data"]["mcp_large_result_guidance"]
    assert guidance["code"] == "report_ai_large_result"
    assert guidance["limited"] is True


@pytest.mark.parametrize("value,expected", [
    (17, 17), (True, None), (17.5, None), ("17", None),
    (0, None), (-1, None), (3601, None), (None, None),
])
def test_retry_after_is_only_bounded_integer(value, expected):
    client = object.__new__(VetmanagerClient)
    data = {"error_code": "CONSTRUCTOR_BUSY"}
    if value is not None:
        data["retry_after_seconds"] = value
    response = httpx.Response(403, json={"message": "busy", "data": data})
    with pytest.raises(VetmanagerError) as error:
        client._raise_for_status(response, path="/rest/api/report/StartReport")
    assert error.value.error_code == "CONSTRUCTOR_BUSY"
    assert error.value.retry_after_seconds == expected


def test_legacy_retry_delay_wrapper_and_not_found_code():
    client = object.__new__(VetmanagerClient)
    with pytest.raises(VetmanagerError) as error:
        client._raise_for_status(httpx.Response(409, json={
            "data": {"error_code": "FILE_NOT_READY", "details": {"retry_after_seconds": 5}}
        }), path="/rest/api/report/reportFile")
    assert error.value.retry_after_seconds == 5
    assert "5 seconds" in str(_safe_export_error(error.value, "file", retry_on_conflict=True))
    with pytest.raises(VetmanagerError) as missing:
        client._raise_for_status(httpx.Response(404, json={
            "data": {"error_code": "NOT_FOUND"}
        }), path="/rest/api/report-ai-job/123")
    assert missing.value.error_code == "NOT_FOUND"
    assert "NOT_FOUND" in str(_safe_export_error(missing.value, "file", retry_on_conflict=True))


def test_unknown_upstream_code_cannot_become_metric_label(caplog):
    service_metrics.record_report_ai_outcome_code(operation="status", code="SQL SELECT secret")
    snapshot = service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"]
    assert snapshot == {"status|unknown": 1}
    assert "SELECT secret" not in caplog.text


def test_malformed_upstream_code_cannot_break_status_observability():
    service_metrics.record_report_ai_outcome_code(operation="status", code=["bad"])
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        "status|unknown": 1
    }


def test_unknown_job_error_code_is_not_echoed_to_agent():
    payload = {"data": {"job": {"status": "failed", "error_code": "SQL SELECT secret",
                                "error_message_safe": "SQLSTATE SELECT secret"}}}
    result = _annotate_report_ai_workarounds(payload)
    assert result["data"]["job"]["error_code"] == "unknown"
    assert "SELECT secret" not in str(result)


@pytest.mark.parametrize("code,status,delay,expected", [
    ("FILE_NOT_READY", 409, 5, "after 5 seconds"),
    ("FILE_BUILD_FAILED", 422, None, "Stop polling"),
    ("RUN_RATE_LIMITED", 403, 41, "Wait 41 seconds"),
    ("REPORT_NOT_ALLOWED_FOR_REST", 403, None, "cannot be exported over REST"),
])
def test_each_export_code_has_its_own_next_action(code, status, delay, expected):
    exc = VetmanagerError("SQLSTATE SELECT secret", status_code=status,
                          error_code=code, retry_after_seconds=delay)
    answer = _safe_export_error(exc, "export", retry_on_conflict=True)
    assert expected in str(answer)
    assert "SELECT secret" not in str(answer)


def test_llm_unavailable_does_not_blame_intent_or_copy_sql():
    payload = {"data": {"job": {"status": "failed", "error_code": "LLM_UNAVAILABLE",
                                "error_message_safe": "SQLSTATE SELECT secret"}}}
    job = _annotate_report_ai_workarounds(payload)["data"]["job"]
    assert job["mcp_workaround"]["code"] == "LLM_UNAVAILABLE"
    assert "same intent" in " ".join(job["mcp_workaround"]["steps"])
    assert "SELECT secret" not in str(job)


def test_known_legacy_intent_rejection_keeps_code_and_next_action():
    payload = {"data": {"job": {"status": "failed", "error_code": "INTENT_REJECTED",
                                "error_message_safe": "SQLSTATE SELECT secret"}}}
    job = _annotate_report_ai_workarounds(payload)["data"]["job"]
    assert job["error_code"] == "INTENT_REJECTED"
    assert "rephrase" in " ".join(job["mcp_workaround"]["steps"]).lower()
    assert "SELECT secret" not in str(job)


@respx.mock
@pytest.mark.asyncio
async def test_reject_failed_response_does_not_return_raw_sql():
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/22/reject").mock(
        return_value=httpx.Response(200, json={"data": {"job": {
            "id": 22, "status": "failed", "error_code": "PREVIEW_FAILED",
            "error_message_safe": "SQLSTATE SELECT secret FROM clients"}}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 22})
    assert "SELECT secret" not in str(result.structured_content)


@respx.mock
@pytest.mark.asyncio
async def test_reject_timeout_is_never_retried():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/reject").mock(
        side_effect=httpx.ReadTimeout("uncertain outcome")
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError):
        await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 22})
    assert route.call_count == 1


@respx.mock
@pytest.mark.asyncio
async def test_reject_409_is_not_retried():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/22/reject").mock(
        return_value=httpx.Response(409, json={"data": {"error_code": "INVALID_TRANSITION"}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError, match="Read the current job status"):
        await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 22})
    assert route.call_count == 1


def test_unknown_start_report_403_never_echoes_sql():
    exc = VetmanagerError("SQLSTATE SELECT secret", status_code=403,
                          error_code="UNRECOGNIZED")
    assert "SELECT secret" not in str(_safe_export_error(exc, "start export"))
