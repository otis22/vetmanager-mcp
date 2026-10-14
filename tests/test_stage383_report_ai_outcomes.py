"""Report AI outcome classes stay bounded across HTTP and job paths."""

import logging

import httpx
import fakeredis
import pytest
import respx
from fastmcp.exceptions import ToolError

import service_metrics
from shared_metric_counters import RedisMetricCounters, wait_pending
from server import mcp
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock


@pytest.mark.parametrize("code,status,upstream,expected", [
    (None, 500, True, "no_code_http_5xx"),
    ("", 403, True, "no_code_http_4xx"),
    (["bad"], None, True, "no_code_no_status"),
    ("SQL SELECT private", 200, True, "unlisted_code_seen"),
    ("unknown", None, True, "unlisted_code_seen"),
    ("scope_denied", 403, False, "local_scope_denied"),
    ("scope_denied", 403, True, "unlisted_code_seen"),
])
def test_bounded_outcome_class_and_safe_log(code, status, upstream, expected, caplog):
    with caplog.at_level(logging.INFO):
        service_metrics.record_report_ai_outcome_code(
            operation="status", code=code, status_code=status,
            upstream_code=upstream, account_id=7, job_id=22,
        )
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        f"status|{expected}": 1,
    }
    event = next(r for r in caplog.records if r.msg == "report_ai_outcome_code")
    assert (event.code, event.account_id, event.job_id) == (expected, 7, 22)
    assert "SELECT private" not in caplog.text


@respx.mock
@pytest.mark.asyncio
async def test_job_http_500_without_body_counts_status_class():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(500))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime, pytest.raises(ToolError):
        await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        "job|no_code_http_5xx": 1,
    }


@respx.mock
@pytest.mark.asyncio
async def test_job_403_observes_code_without_changing_public_error(caplog):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(
        403, json={"data": {"error_code": "UNLISTED private SQL"}}))
    headers, runtime = bearer_runtime_patch()
    with caplog.at_level(logging.INFO), headers, runtime, pytest.raises(ToolError) as error:
        await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert "unknown" in str(error.value)
    assert "UNLISTED" not in str(error.value) + caplog.text
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        "job|unlisted_code_seen": 1,
    }


@respx.mock
@pytest.mark.asyncio
async def test_failed_job_malformed_code_is_no_status_after_public_annotation():
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(200, json={
        "data": {"job": {"id": 22, "status": "failed", "error_code": ["private"]}}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert result.structured_content["data"]["job"]["error_code"] == "unknown"
    assert service_metrics.snapshot_service_metrics()["report_ai_outcomes_by_code_total"] == {
        "status|no_code_no_status": 1,
    }


@respx.mock
@pytest.mark.asyncio
async def test_failed_job_log_has_request_ids_before_redis_callback(caplog, monkeypatch):
    from tools import report_ai

    monkeypatch.setenv("WEB_SESSION_SECRET", "stage383-report-ai-test-secret")
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(client)
    queued = []
    monkeypatch.setattr(report_ai.shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(report_ai.shared_metric_counters, "dispatch",
                        lambda fn, *, on_full=None: queued.append(fn))
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/22").mock(return_value=httpx.Response(200, json={
        "data": {"job": {"id": 22, "status": "failed", "error_code": "FUTURE_CODE"}}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 22})
    assert result.structured_content["data"]["job"]["error_code"] == "unknown"
    with caplog.at_level(logging.INFO):
        while queued:
            queued.pop(0)()
    event = next(r for r in caplog.records if r.msg == "report_ai_outcome_code")
    assert (event.code, event.account_id, event.job_id) == ("unlisted_code_seen", 1, 22)
    assert backend.snapshot()["report_ai_outcomes_by_code_total"] == {
        "status|unlisted_code_seen": 1,
    }
    assert not [r for r in caplog.records if r.msg in {
        "report_ai_observation_failed", "Shared metric event lost",
    }]
    assert "FUTURE_CODE" not in caplog.text
    client.close()


@pytest.mark.asyncio
async def test_new_classes_share_one_redis_counter_across_slots(monkeypatch):
    server = fakeredis.FakeServer()
    client_a = fakeredis.FakeRedis(server=server, decode_responses=True)
    client_b = fakeredis.FakeRedis(server=server, decode_responses=True)
    slot_a = RedisMetricCounters(client_a)
    slot_b = RedisMetricCounters(client_b)
    active = [slot_a]
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: active[0])
    service_metrics.record_report_ai_outcome_code(operation="job", code=None, status_code=500)
    await wait_pending()
    active[0] = slot_b
    service_metrics.record_report_ai_outcome_code(operation="job", code="FUTURE_CODE",
                                                   upstream_code=True)
    await wait_pending()
    expected = {"job|no_code_http_5xx": 1, "job|unlisted_code_seen": 1}
    assert slot_a.snapshot()["report_ai_outcomes_by_code_total"] == expected
    assert slot_b.snapshot()["report_ai_outcomes_by_code_total"] == expected
    assert "no_code_http_5xx" in service_metrics.render_prometheus_metrics()
    client_a.close()
    client_b.close()
