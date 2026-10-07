"""Stage 369: one bounded wait must lead to an explicit safe next action."""

import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from prompts import get_report_ai_prompt_helper_text
import service_metrics
import tools as tool_module
import tools.report_ai as report_ai
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS
from token_scopes import SCOPE_REPORT_AI_WRITE


@pytest.fixture(autouse=True)
def _isolate_known_issue_lookup(monkeypatch):
    async def unchanged(_tool_name, _credentials, exc, **_kwargs):
        return exc

    monkeypatch.setattr(tool_module, "augment_tool_error", unchanged)


def _job(status, *, job_id=369, **fields):
    return {"success": True, "data": {"job": {"id": job_id, "status": status, **fields}}}


def _result(result):
    return result.structured_content["data"]["job"]


def test_prompt_helper_carries_bounded_journey_and_preview_boundary():
    helper = get_report_ai_prompt_helper_text()
    journey = helper.split("## Report AI journey", 1)[1].split("\n## ", 1)[0]
    steps = (
        "create_report_ai_job(wait_seconds=30)",
        "get_report_ai_job(wait_seconds=30)",
        "needs_confirmation",
        "confirm_report_ai_job_candidate",
        "reject_report_ai_job_candidate",
        "save_report_ai_job_as_report",
        "get_report_ai_job_data",
    )
    assert all(step in journey for step in steps)
    assert [journey.index(step) for step in steps] == sorted(journey.index(step) for step in steps)
    assert "preview_summary" in journey and "preview_example_row" in journey
    assert "Нельзя отвечать пользователю по превью" in journey
    assert "manual poll" not in journey.lower()
    descriptions = " ".join(SPECIAL_TOOL_DESCRIPTIONS[name] for name in (
        "create_report_ai_job", "get_report_ai_prompt_helper", "get_report_ai_job",
    ))
    assert "preview_summary" in descriptions and "preview_example_row" in descriptions
    assert "Do not answer the user from either preview field" in descriptions


@pytest.mark.asyncio
@respx.mock
async def test_create_wait_uses_one_post_and_reaches_ready_with_save_call(monkeypatch):
    billing_mock()
    report_ai._reset_report_ai_queue_observations()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )
    get = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(side_effect=[
        httpx.Response(200, json=_job("recognizing")),
        httpx.Response(200, json=_job("ready_to_save")),
    ])

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep, raising=False)
    queue_diagnostics = AsyncMock(return_value=_job("queued"))
    monkeypatch.setattr(report_ai, "_annotate_report_ai_queue_diagnostics", queue_diagnostics)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 30,
        })
    job = _result(result)
    assert post.call_count == 1
    assert get.call_count == 2
    assert job["status"] == "ready_to_save"
    assert job["next_action"]["call"]["tool"] == "save_report_ai_job_as_report"
    assert job["next_action"]["call"]["arguments"]["job_id"] == 369
    assert report_ai._report_ai_queue_observation_count() == 0
    queue_diagnostics.assert_not_awaited()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad_response", [
    httpx.Response(200, text="invalid-json"),
    httpx.Response(200, json=None),
    httpx.Response(200, json={}),
])
async def test_create_wait_preserves_job_id_on_malformed_poll(monkeypatch, bad_response):
    billing_mock()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )
    get = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(return_value=bad_response)

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 30,
        })
    job = _result(result)
    assert post.call_count == 1 and get.call_count == 1
    assert job["id"] == 369 and job["status"] == "queued"
    assert job["mcp_wait_diagnostics"]["code"] == "poll_failed"


@pytest.mark.asyncio
@respx.mock
async def test_wait_timeout_keeps_same_job_and_never_recreates():
    billing_mock()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )
    get = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("queued"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 1,
        })
    job = _result(result)
    assert post.call_count == 1
    assert get.call_count <= 1
    assert job["id"] == 369
    assert job["mcp_wait_diagnostics"]["code"] == "wait_timeout"
    assert "get_report_ai_job" in job["mcp_wait_diagnostics"]["next_step"]


@pytest.mark.asyncio
@respx.mock
async def test_cancel_after_create_response_never_replays_post(monkeypatch):
    billing_mock()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )
    get = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("queued"))
    )

    async def cancelled(_seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", cancelled)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(asyncio.CancelledError):
        await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 30,
        })
    assert post.call_count == 1
    assert get.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_wait_stops_on_429_without_transport_retry(monkeypatch):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(side_effect=[
        httpx.Response(200, json=_job("queued")),
        httpx.Response(429, json={"data": {"error_code": "RUN_RATE_LIMITED"}}),
    ])

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep, raising=False)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 369, "wait_seconds": 30})
    job = _result(result)
    assert route.call_count == 2
    assert job["id"] == 369
    assert job["mcp_wait_diagnostics"]["code"] == "poll_failed"


@pytest.mark.asyncio
@respx.mock
async def test_first_get_wait_timeout_names_same_job_without_new_status():
    billing_mock()

    async def slow(_request):
        await asyncio.sleep(2)
        return httpx.Response(200, json=_job("ready_to_save"))

    route = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(side_effect=slow)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("get_report_ai_job", {"job_id": 369, "wait_seconds": 1})
    assert route.call_count <= 1
    assert "369" in str(error.value) and "same job" in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_wait_reaches_confirmation_and_returns_both_choices(monkeypatch):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(side_effect=[
        httpx.Response(200, json=_job("building_preview")),
        httpx.Response(200, json=_job("needs_confirmation", candidates=[{"report_id": 84}])),
    ])

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 369, "wait_seconds": 30})
    assert route.call_count == 2
    job = _result(result)
    assert job["status"] == "needs_confirmation"
    assert {call["tool"] for call in job["next_action"]["calls"]} == {
        "confirm_report_ai_job_candidate", "reject_report_ai_job_candidate",
    }


@pytest.mark.asyncio
@respx.mock
async def test_reject_followed_by_stale_confirmation_only_suggests_poll():
    billing_mock()
    report_ai._reset_report_ai_queue_observations()
    respx.post(f"{BASE}/rest/api/report-ai-job/369/reject").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        rejected = await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 369})
        stale = await mcp.call_tool("get_report_ai_job", {"job_id": 369})
    assert _result(rejected)["next_action"]["type"] == "wait_after_reject"
    assert _result(stale)["next_action"]["call"]["tool"] == "get_report_ai_job"
    assert "reject_report_ai_job_candidate" not in str(_result(stale)["next_action"])


@pytest.mark.asyncio
@respx.mock
async def test_failed_reject_response_does_not_hide_confirmation_choice():
    billing_mock()
    report_ai._reset_report_ai_queue_observations()
    respx.post(f"{BASE}/rest/api/report-ai-job/369/reject").mock(
        return_value=httpx.Response(200, json={"success": False, "data": {"job": {
            "id": 369, "status": "needs_confirmation",
        }}})
    )
    respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError):
            await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 369})
        current = await mcp.call_tool("get_report_ai_job", {"job_id": 369})
    assert "reject_report_ai_job_candidate" in str(_result(current)["next_action"])


@pytest.mark.asyncio
@respx.mock
async def test_wait_validation_and_rollback_do_not_write(monkeypatch):
    billing_mock()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )
    get = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("queued"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError):
            await mcp.call_tool("create_report_ai_job", {
                "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 31,
            })
        monkeypatch.setenv("REPORT_AI_WAIT_ENABLED", "0")
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 30,
        })
    assert post.call_count == 1
    assert get.call_count == 0
    assert _result(result)["status"] == "queued"


@pytest.mark.asyncio
@respx.mock
async def test_create_with_write_only_scope_returns_id_when_wait_read_is_denied(monkeypatch):
    billing_mock()
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json=_job("queued"))
    )

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep)
    headers, runtime = bearer_runtime_patch(scopes=(SCOPE_REPORT_AI_WRITE,))
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество счетов за май 1900 года", "wait_seconds": 30,
        })
    job = _result(result)
    assert post.call_count == 1
    assert job["id"] == 369
    assert job["mcp_wait_diagnostics"]["code"] == "missing_analytics_scope"
    assert "analytics.read" in job["mcp_wait_diagnostics"]["next_step"]


@pytest.mark.asyncio
@respx.mock
async def test_internal_wait_polls_do_not_repeat_queue_stall_warning(monkeypatch, caplog):
    billing_mock()
    report_ai._reset_report_ai_queue_observations()
    route = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("queued"))
    )

    async def no_sleep(_seconds):
        pass

    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", no_sleep)
    monkeypatch.setattr(report_ai, "REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS", 0)
    headers, runtime = bearer_runtime_patch()
    with caplog.at_level("WARNING", logger="vetmanager.runtime"), headers, runtime:
        await mcp.call_tool("get_report_ai_job", {"job_id": 369, "wait_seconds": 30})
    warnings = [record for record in caplog.records
                if getattr(record, "event_name", None) == "report_ai_job_long_queued"]
    assert len(warnings) <= 2
    assert route.call_count <= report_ai.REPORT_AI_TOOL_WAIT_MAX_GETS


def test_needs_confirmation_calls_are_bounded_to_upstream_candidate_ids():
    payload = _job("needs_confirmation", candidates=[
        {"report_id": 84, "title": "Old report"},
        {"report_id": "private-string"},
    ])
    job = report_ai._annotate_report_ai_workarounds(payload)["data"]["job"]
    calls = job["next_action"]["calls"]
    assert {call["tool"] for call in calls} == {
        "confirm_report_ai_job_candidate", "reject_report_ai_job_candidate",
    }
    assert [call["arguments"]["report_id"] for call in calls
            if call["tool"] == "confirm_report_ai_job_candidate"] == [84]
    assert "private-string" not in str(calls)


@pytest.mark.asyncio
@respx.mock
async def test_save_refusal_names_both_choices_only_after_fresh_confirmation_status():
    billing_mock()
    save = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(409, json={"data": {"error_code": "INVALID_TRANSITION"}})
    )
    view = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    assert save.call_count == 1
    assert view.call_count == 1
    assert "confirm_report_ai_job_candidate" in str(error.value)
    assert "reject_report_ai_job_candidate" in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_save_refusal_after_reject_suggests_poll_only():
    billing_mock()
    report_ai._reset_report_ai_queue_observations()
    respx.post(f"{BASE}/rest/api/report-ai-job/369/reject").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(409, json={"data": {"error_code": "INVALID_TRANSITION"}})
    )
    respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("needs_confirmation"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 369})
        with pytest.raises(ToolError) as error:
            await mcp.call_tool("save_report_ai_job_as_report", {
                "job_id": 369, "title": "MCP invoices May 1900",
            })
    assert "get_report_ai_job" in str(error.value)
    assert "confirm_report_ai_job_candidate" not in str(error.value)
    assert "reject_report_ai_job_candidate" not in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_unknown_save_outcomes_require_read_before_retry():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        side_effect=[
            httpx.Response(503, json={"data": {"error_code": "SAVE_FAILED"}}),
            httpx.Response(200, json={"success": True, "data": {}}),
        ]
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        for _ in range(2):
            with pytest.raises(ToolError) as error:
                await mcp.call_tool("save_report_ai_job_as_report", {
                    "job_id": 369, "title": "MCP invoices May 1900",
                })
            assert "get_report_ai_job" in str(error.value)
            assert "automatically" in str(error.value)
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("bad_response", [
    httpx.Response(200, text="invalid-json"),
    httpx.Response(200, json=None),
    httpx.Response(200, json=[]),
])
async def test_malformed_save_success_requires_read_before_retry(bad_response):
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=bad_response
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    assert route.call_count == 1
    assert "get_report_ai_job" in str(error.value)
    assert "automatically" in str(error.value)


@pytest.mark.asyncio
@respx.mock
async def test_save_without_report_id_does_not_suggest_second_save():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(200, json=_job("ready_to_save"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    job = _result(result)
    assert route.call_count == 1
    assert job["next_action"]["call"]["tool"] == "get_report_ai_job"
    assert "automatically" in job["next_action"]["guidance"]


@pytest.mark.asyncio
@respx.mock
async def test_save_refusal_queued_does_not_propose_candidate_writes():
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(409, json={"data": {"error_code": "INVALID_TRANSITION"}})
    )
    view = respx.get(f"{BASE}/rest/api/report-ai-job/369").mock(
        return_value=httpx.Response(200, json=_job("queued"))
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    assert "confirm_report_ai_job_candidate" not in str(error.value)
    assert "reject_report_ai_job_candidate" not in str(error.value)
    assert view.call_count == 1


def test_public_descriptions_make_preview_and_wait_contract_explicit():
    create = SPECIAL_TOOL_DESCRIPTIONS["create_report_ai_job"]
    status = SPECIAL_TOOL_DESCRIPTIONS["get_report_ai_job"]
    data = SPECIAL_TOOL_DESCRIPTIONS["get_report_ai_job_data"]
    assert "wait_seconds" in create and "wait_seconds" in status
    assert "preview_summary" in status and "preview_example_row" in status
    assert "not live" in status.lower() and "do not answer" in status.lower()
    assert "get_report_ai_job_data" in status and "save" in data


def test_save_metric_rejects_dynamic_outcome_labels():
    service_metrics.reset_service_metrics()
    service_metrics.record_report_ai_save_attempt(outcome="secret-patient-id")
    service_metrics.record_report_ai_save_attempt(outcome=["secret-patient-id"])
    snapshot = service_metrics.snapshot_service_metrics()["report_ai_save_attempts_total"]
    assert snapshot == {"unknown": 2}
    rendered = service_metrics.render_prometheus_metrics()
    assert "secret-patient-id" not in rendered
    assert 'vetmanager_report_ai_save_attempts_total{outcome="unknown"} 2' in rendered


@pytest.mark.asyncio
@respx.mock
async def test_save_success_records_attempt_and_terminal_without_followup_get():
    service_metrics.reset_service_metrics()
    report_ai._reset_report_ai_queue_observations()
    billing_mock()
    save = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(200, json={
            "success": True, "data": {"report_id": 84, "is_idempotent": False},
        })
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    assert save.call_count == 1
    assert result.structured_content["data"]["report_id"] == 84
    snapshot = service_metrics.snapshot_service_metrics()
    assert snapshot["report_ai_save_attempts_total"] == {"success": 1}
    assert snapshot["report_ai_job_terminal_outcomes_total"].get("saved") == 1


@pytest.mark.asyncio
@respx.mock
async def test_confirm_without_followup_get_records_existing_match():
    service_metrics.reset_service_metrics()
    report_ai._reset_report_ai_queue_observations()
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/369/confirm").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"report_id": 84}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool("confirm_report_ai_job_candidate", {"job_id": 369, "report_id": 84})
    snapshot = service_metrics.snapshot_service_metrics()
    assert snapshot["report_ai_job_terminal_outcomes_total"].get("existing_report_matched") == 1


@pytest.mark.asyncio
@respx.mock
async def test_save_attempt_outcomes_are_bounded_and_no_input_is_label():
    service_metrics.reset_service_metrics()
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(side_effect=[
        httpx.Response(200, json={"success": False, "data": {"error_code": "SAVE_FAILED"}}),
        httpx.ReadTimeout("private-patient-name"),
    ])
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(ToolError):
            await mcp.call_tool("save_report_ai_job_as_report", {"job_id": 369, "title": "report"})
        with pytest.raises(ToolError):
            await mcp.call_tool("save_report_ai_job_as_report", {
                "job_id": 369, "title": "MCP invoices May 1900",
            })
        with pytest.raises(ToolError):
            await mcp.call_tool("save_report_ai_job_as_report", {
                "job_id": 369, "title": "MCP invoices June 1900",
            })
    assert route.call_count == 2
    assert service_metrics.snapshot_service_metrics()["report_ai_save_attempts_total"] == {
        "error": 1, "invalid_input": 1, "unknown": 1,
    }
    assert "private-patient-name" not in service_metrics.render_prometheus_metrics()


@pytest.mark.asyncio
@respx.mock
async def test_save_5xx_with_known_code_is_still_unknown_outcome():
    service_metrics.reset_service_metrics()
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/report-ai-job/369/save").mock(
        return_value=httpx.Response(503, json={"data": {"error_code": "SAVE_FAILED"}})
    )
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError):
        await mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 369, "title": "MCP invoices May 1900",
        })
    assert route.call_count == 1
    assert service_metrics.snapshot_service_metrics()["report_ai_save_attempts_total"] == {"unknown": 1}
