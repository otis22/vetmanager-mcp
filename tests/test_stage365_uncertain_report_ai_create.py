"""A failed create must remain diagnosable without replaying a write."""

from unittest.mock import patch
import re

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import agent_feedback_service
import service_metrics
import tools as tool_module
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from vm_transport.retry import MAX_RETRIES_WRITE


SECRET = "private-intent-and-upstream-message"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("response,expected_code,status", [
    (httpx.ReadTimeout("secret transport detail"), "REPORT_AI_CREATE_TIMEOUT", None),
    (httpx.ConnectError("secret transport detail"), "REPORT_AI_CREATE_NETWORK_UNKNOWN", None),
    (httpx.Response(503, json={"message": SECRET}), "REPORT_AI_CREATE_HTTP_5XX", 503),
    (httpx.Response(200, text="bad json " + SECRET), "REPORT_AI_CREATE_RESPONSE_UNKNOWN", 200),
    (httpx.Response(204), "REPORT_AI_CREATE_RESPONSE_UNKNOWN", 204),
    (httpx.Response(200, json={"success": True, "data": {}}), "REPORT_AI_CREATE_RESPONSE_UNKNOWN", 200),
])
async def test_uncertain_create_is_safe_and_not_replayed(response, expected_code, status, caplog):
    assert MAX_RETRIES_WRITE == 0
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job")
    if isinstance(response, Exception):
        route.mock(side_effect=response)
    else:
        route.mock(return_value=response)
    incident = []

    async def capture_feedback(tool_name, credentials, exc, *, incident_source=None, **kwargs):
        assert tool_name == "create_report_ai_job"
        incident.append(agent_feedback_service.build_incident_from_exception(tool_name, incident_source or exc))
        return exc

    headers, runtime = bearer_runtime_patch()
    with patch.object(tool_module, "augment_tool_error", capture_feedback):
        with headers, runtime:
            with pytest.raises(ToolError) as caught:
                await mcp.call_tool("create_report_ai_job", {"intent_text": SECRET})

    assert route.call_count == 1
    correlation = route.calls.last.request.headers["X-Correlation-ID"]
    message = str(caught.value)
    assert expected_code in message
    assert f"class {expected_code.removeprefix('REPORT_AI_CREATE_').lower()}" in message
    assert correlation in message
    assert "uncertain" in message.lower()
    assert "get_report_ai_job" in message
    assert "do not" in message.lower() and "post" in message.lower()
    assert SECRET not in message
    assert "secret transport detail" not in message
    assert incident[0].error_code == expected_code
    assert incident[0].http_status == status
    assert correlation in (agent_feedback_service.sanitize_text(incident[0].error_excerpt, limit=1000) or "")
    assert SECRET not in incident[0].error_excerpt
    assert SECRET not in caplog.text
    assert "secret transport detail" not in caplog.text
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        f"job|{expected_code}": 1,
    }


@pytest.mark.asyncio
@respx.mock
async def test_open_breaker_is_not_an_uncertain_create(monkeypatch):
    from exceptions import VetmanagerUpstreamUnavailable
    import vetmanager_client

    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": {"id": 1}}})
    )

    async def refuse(_domain):
        raise VetmanagerUpstreamUnavailable("breaker is open")

    monkeypatch.setattr(vetmanager_client, "_check_breaker_allows", refuse)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as caught:
        await mcp.call_tool("create_report_ai_job", {"intent_text": "Число клиентов за 1900 год"})
    assert route.call_count == 0
    assert "REPORT_AI_CREATE_" not in str(caught.value)
    assert "was not sent" in str(caught.value)
    assert "uncertain" not in str(caught.value)


@pytest.mark.asyncio
@respx.mock
async def test_known_create_validation_error_keeps_existing_code():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(400, json={
            "success": False, "message": SECRET,
            "data": {"error_code": "VALIDATION_ERROR"},
        })
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError) as caught:
            await mcp.call_tool("create_report_ai_job", {"intent_text": "Количество клиентов за 1900 год"})
    assert route.call_count == 1
    assert "VALIDATION_ERROR" in str(caught.value)
    assert "REPORT_AI_CREATE_" not in str(caught.value)
    assert SECRET not in str(caught.value)


@pytest.mark.asyncio
@respx.mock
async def test_sibling_job_read_does_not_get_create_error_code():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/42").mock(
        return_value=httpx.Response(503, json={"message": SECRET})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError) as caught:
            await mcp.call_tool("get_report_ai_job", {"job_id": 42})
    assert route.call_count >= 1
    assert "REPORT_AI_CREATE_" not in str(caught.value)
    assert "list recent jobs" not in str(caught.value)


@pytest.mark.asyncio
@respx.mock
async def test_legacy_top_level_job_id_remains_a_success():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={
            "success": True, "job": {"id": 36501, "status": "queued"},
        })
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool(
            "create_report_ai_job", {"intent_text": "Количество счетов за 1900 год"}
        )
    assert route.call_count == 1
    assert result.structured_content["job"]["id"] == 36501


@pytest.mark.asyncio
@respx.mock
async def test_caller_chosen_correlation_is_not_exposed(monkeypatch, caplog):
    import vetmanager_client

    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(503, json={"message": SECRET})
    )
    caller_value = "PrivatePatientSmith"
    monkeypatch.setattr(vetmanager_client, "get_current_request_context",
                        lambda: {"correlation_id": caller_value})
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError) as caught:
            await mcp.call_tool("create_report_ai_job", {"intent_text": "Количество за 1900 год"})
    correlation = route.calls.last.request.headers["X-Correlation-ID"]
    assert re.fullmatch(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}", correlation)
    assert correlation in str(caught.value)
    assert caller_value not in str(caught.value)
    assert caller_value not in caplog.text
