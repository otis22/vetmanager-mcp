"""Stage 455: long bounded Report AI waits preserve continuation and consent."""

import copy
from unittest.mock import AsyncMock

import pytest

from exceptions import ToolInputError
import tools.report_ai as report_ai
from tests.test_stage170_report_ai_tools import bearer_runtime_patch


def test_wait_accepts_thirty_minutes_but_rejects_above_boundary():
    assert report_ai._validate_report_ai_wait_seconds(1800) == 1800
    for invalid in (1801, -1, True):
        with pytest.raises(ToolInputError):
            report_ai._validate_report_ai_wait_seconds(invalid)


@pytest.mark.asyncio
async def test_long_wait_keeps_polling_past_thirty_seconds_and_sixteen_gets(monkeypatch):
    clock = [0.0]
    calls = []
    payload = {"data": {"job": {"id": 455, "status": "recognizing"}}}

    async def sleep(seconds):
        clock[0] += seconds

    async def get(method, path, **kwargs):
        calls.append((method, path))
        result = copy.deepcopy(payload)
        if clock[0] >= 1200:
            result["data"]["job"]["status"] = "ready_to_save"
        return result

    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: clock[0])
    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", sleep)
    monkeypatch.setattr(report_ai, "_annotate_report_ai_wait_payload", AsyncMock(side_effect=lambda x: x))
    monkeypatch.setattr(report_ai, "_call_vm", get)
    result = await report_ai._wait_for_report_ai_job(payload, job_id=455, deadline=1800)
    assert result["data"]["job"]["status"] == "ready_to_save"
    assert "mcp_wait_diagnostics" not in result["data"]["job"]
    assert 16 < len(calls) <= 1000
    assert clock[0] == 1200
    assert all(method == "GET" and path.endswith("/455") for method, path in calls)


@pytest.mark.asyncio
async def test_last_permitted_poll_returns_human_action_without_timeout(monkeypatch):
    payload = {"data": {"job": {"id": 455, "status": "queued"}}}
    done = {"data": {"job": {"id": 455, "status": "needs_confirmation"}}}
    monkeypatch.setattr(report_ai, "_report_ai_wait_sleep", AsyncMock())
    monkeypatch.setattr(report_ai, "_annotate_report_ai_wait_payload", AsyncMock(side_effect=lambda x: x))
    monkeypatch.setattr(report_ai, "_call_vm", AsyncMock(return_value=done))
    result = await report_ai._wait_for_report_ai_job(
        payload, job_id=455, deadline=report_ai._monotonic_seconds() + 1800, max_gets=1)
    assert result["data"]["job"]["status"] == "needs_confirmation"
    assert "mcp_wait_diagnostics" not in result["data"]["job"]


def test_short_timeout_continues_same_job_but_network_error_pauses():
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        job = {"id": 455, "status": "recognizing", "mcp_wait_diagnostics": {"code": "wait_timeout"}}
        report_ai._annotate_report_ai_next_action(job)
        assert job["next_action"]["type"] == "poll"
        assert job["next_action"]["call"]["arguments"] == {"job_id": 455, "wait_seconds": 1800}
        job["mcp_wait_diagnostics"]["code"] = "poll_failed"
        report_ai._annotate_report_ai_next_action(job)
        assert job["next_action"]["type"] == "poll_paused"
        assert "call" not in job["next_action"]


@pytest.mark.asyncio
async def test_stage_at_twenty_minutes_is_not_declared_stale(monkeypatch):
    report_ai._reset_report_ai_queue_observations()
    clock = [0.0]
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: clock[0])
    payload = {"data": {"job": {"id": 455, "status": "recognizing"}}}
    await report_ai._annotate_report_ai_wait_payload(copy.deepcopy(payload))
    clock[0] = 1200.0
    result = await report_ai._annotate_report_ai_wait_payload(copy.deepcopy(payload))
    assert not result["data"]["job"].get("mcp_queue_diagnostics", {}).get("stop_automatic_polling")
    clock[0] = 1800.0
    result = await report_ai._annotate_report_ai_wait_payload(copy.deepcopy(payload))
    assert result["data"]["job"]["mcp_queue_diagnostics"]["stop_automatic_polling"] is True
    report_ai._reset_report_ai_queue_observations()
