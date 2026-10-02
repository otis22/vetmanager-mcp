"""A successful Report AI upstream call must keep its result when accounting fails."""

import logging
from unittest.mock import MagicMock, patch

import httpx
import pytest
import respx

import clinic_timezone
import error_tracking
import service_metrics
import tools.report_ai as report_ai
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock


JOB = {"id": 35201, "status": "queued"}


class ClinicClient:
    async def get(self, path):
        assert path == "/rest/api/clinics/7"
        return {"data": {"clinics": {"time_zone": "Europe/Moscow"}}}


@pytest.mark.asyncio
@respx.mock
async def test_create_returns_job_id_after_real_timezone_resolver_populates_cache():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": JOB}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        assert await clinic_timezone.resolve_clinic_timezone(7, client_factory=ClinicClient)
        assert clinic_timezone._CACHE
        result = await mcp.call_tool(
            "create_report_ai_job", {"intent_text": "Количество счетов за май 2026"}
        )

    assert route.call_count == 1
    assert result.structured_content["data"]["job"]["id"] == JOB["id"]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("tool_name,arguments,method,path", [
    ("create_report_ai_job", {"intent_text": "Количество счетов за май 2026"}, "post", "/rest/api/report-ai-job"),
    ("get_report_ai_job", {"job_id": 35201}, "get", "/rest/api/report-ai-job/35201"),
    ("confirm_report_ai_job_candidate", {"job_id": 35201, "report_id": 8}, "post", "/rest/api/report-ai-job/35201/confirm"),
    ("reject_report_ai_job_candidate", {"job_id": 35201}, "post", "/rest/api/report-ai-job/35201/reject"),
    ("save_report_ai_job_as_report", {"job_id": 35201, "title": "MCP invoices May 2026"}, "post", "/rest/api/report-ai-job/35201/save"),
])
async def test_lifecycle_failure_keeps_upstream_result_and_is_reported(
    monkeypatch, caplog, tool_name, arguments, method, path
):
    billing_mock()
    route = getattr(respx, method)(f"{BASE}{path}").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": JOB}})
    )
    secret = "clinic-secret-in-observation"

    def broken(*_args, **_kwargs):
        raise RuntimeError(secret)

    monkeypatch.setattr(report_ai, "_observe_report_ai_lifecycle", broken)
    headers, runtime = bearer_runtime_patch()
    with patch.object(report_ai, "capture_report_ai_observation_failure") as captured:
        with caplog.at_level(logging.WARNING):
            with headers, runtime:
                result = await mcp.call_tool(tool_name, arguments)

    assert route.call_count == 1
    assert result.structured_content["data"]["job"]["id"] == JOB["id"]
    assert any(getattr(record, "event_name", None) == "report_ai_observation_failed" for record in caplog.records)
    assert secret not in caplog.text
    captured.assert_called_once()


@pytest.mark.asyncio
@respx.mock
async def test_tool_call_metric_failure_cannot_hide_created_job(monkeypatch):
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": JOB}})
    )
    monkeypatch.setattr(service_metrics, "record_tool_call", lambda **kw: (_ for _ in ()).throw(RuntimeError("metric failed")))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool(
            "create_report_ai_job", {"intent_text": "Количество счетов за май 2026"}
        )
    assert route.call_count == 1
    assert result.structured_content["data"]["job"]["id"] == JOB["id"]


@pytest.mark.asyncio
async def test_shared_instrumentation_default_keeps_existing_failure_contract(monkeypatch):
    def broken(**_kwargs):
        raise RuntimeError("metric failed")

    async def request():
        return {"ok": True}

    monkeypatch.setattr(service_metrics, "record_tool_call", broken)
    with pytest.raises(RuntimeError, match="metric failed"):
        await service_metrics.instrument_call("/other", "GET", request)


@pytest.mark.asyncio
@respx.mock
async def test_status_after_create_accounting_failure_uses_same_job_id(monkeypatch):
    billing_mock()
    create = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": JOB}})
    )
    status = respx.get(f"{BASE}/rest/api/report-ai-job/{JOB['id']}").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"job": JOB}})
    )
    original = report_ai._observe_report_ai_lifecycle
    calls = 0

    def fail_once(job, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("clinic-private-data")
        return original(job, **kwargs)

    monkeypatch.setattr(report_ai, "_observe_report_ai_lifecycle", fail_once)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        created = await mcp.call_tool(
            "create_report_ai_job", {"intent_text": "Количество счетов за май 2026"}
        )
        viewed = await mcp.call_tool("get_report_ai_job", {"job_id": JOB["id"]})
    assert create.call_count == status.call_count == 1
    assert created.structured_content["data"]["job"]["id"] == JOB["id"]
    assert viewed.structured_content["data"]["job"]["id"] == JOB["id"]


@pytest.mark.asyncio
@respx.mock
async def test_export_success_metric_failure_keeps_file_id(monkeypatch):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {
            "report": {"report_file_id": 35202}
        }})
    )
    monkeypatch.setattr(report_ai, "record_report_ai_export", lambda **kw: (_ for _ in ()).throw(RuntimeError("metric failed")))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("start_report_export", {"report_id": 88})
    assert route.call_count == 1
    assert result.structured_content["data"]["report"]["report_file_id"] == 35202


def test_sentry_observation_event_contains_no_exception_text_or_stack(monkeypatch):
    scope = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = scope
    monkeypatch.setattr(error_tracking, "_configured", True)
    monkeypatch.setattr(error_tracking.sentry_sdk, "is_initialized", lambda: True)
    with (
        patch.object(error_tracking.sentry_sdk, "push_scope", return_value=context),
        patch.object(error_tracking.sentry_sdk, "capture_message") as message,
        patch.object(error_tracking.sentry_sdk, "capture_exception") as exception,
    ):
        error_tracking.capture_report_ai_observation_failure(
            RuntimeError("clinic-secret-in-observation"), operation="create_lifecycle"
        )
    message.assert_called_once_with("report_ai_observation_failed", level="error")
    exception.assert_not_called()
    scope.clear_breadcrumbs.assert_called_once_with()
    scope.set_tag.assert_any_call("operation", "create_lifecycle")
    scope.set_tag.assert_any_call("exc_type", "RuntimeError")

    sanitized = error_tracking._sanitize_event({
        "tags": {"report_ai_observation_failure": "true", "operation": "create_lifecycle"},
        "request": {"data": {"intent_text": "clinic-secret-in-observation"}},
        "contexts": {"response": {"job": "clinic-secret-in-observation"}},
        "breadcrumbs": {"values": [{"message": "clinic-secret-in-observation"}]},
        "logentry": {"message": "report_ai_observation_failed"},
    }, hint={})
    assert "clinic-secret-in-observation" not in str(sanitized)
