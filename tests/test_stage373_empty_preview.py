"""Stage 373: bounded guidance observations and outcome attribution."""

import httpx
import pytest
import respx

import service_metrics as metrics
import tools.report_ai as report_ai
from runtime_auth import use_runtime_credentials
from server import mcp
from tests.runtime_factories import make_runtime_credentials
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock

ZERO = "Превью: 0 строк, 3 колонки"
NONZERO = "Превью: 2 строк, 3 колонки"


@pytest.fixture(autouse=True)
def clean():
    report_ai._reset_report_ai_queue_observations()
    metrics.reset_service_metrics()
    yield
    report_ai._reset_report_ai_queue_observations()
    metrics.reset_service_metrics()


def as_account(account=1, connection=1):
    return use_runtime_credentials(make_runtime_credentials("example", "test", account_id=account, connection_id=connection))


def job(job_id, status="ready_to_save", summary=ZERO, **fields):
    return {"id": job_id, "status": status, "preview_summary": summary, **fields}


def issue(item, now):
    report_ai._observe_report_ai_lifecycle(item, now=now)
    payload = report_ai._annotate_report_ai_workarounds({"data": {"job": item}})
    report_ai._issued_empty_preview_guidance(payload)


def counts():
    snap = metrics.snapshot_service_metrics()
    return (snap["report_ai_empty_preview_guidance_issued_total"],
            snap["report_ai_empty_preview_guidance_jobs_total"],
            snap["report_ai_empty_preview_guidance_outcomes_total"])


def test_first_issue_repeat_keeps_fixed_window(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: clock[0])
    with as_account(connection=1):
        issue(job(1), clock[0])
    clock[0] = 3500.0
    with as_account(connection=1):
        issue(job(1), clock[0])
    assert counts()[:2] == (2, 1)
    clock[0] = 3701.0
    with as_account(connection=1):
        report_ai._cleanup_report_ai_queue_observations(clock[0])
    assert counts()[2] == {"abandoned_wait": 1}


def test_issue_cross_connection_is_one_logical_job(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    with as_account(connection=1):
        issue(job(1), 100.0)
    with as_account(connection=2):
        issue(job(1), 100.0)
    assert counts()[:2] == (2, 1)


def test_recreated_cross_connection_excludes_dedup_same_id_and_other_account(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    with as_account(1, 1):
        issue(job(1), 100.0)
    with as_account(2, 1):
        report_ai._match_recreated_report_ai_job(job(2))
    with as_account(1, 2):
        report_ai._match_recreated_report_ai_job(job(2, is_deduplicated=True))
        report_ai._match_recreated_report_ai_job(job(1))
    assert counts()[2] == {}
    with as_account(1, 2):
        report_ai._match_recreated_report_ai_job(job(2))
        report_ai._match_recreated_report_ai_job(job(3))
    assert counts()[2] == {"recreated": 1}


def test_saved_without_get_cross_connection_uses_last_definite_preview(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    with as_account(connection=1):
        issue(job(1), 100.0)
    with as_account(connection=2):
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=101.0)
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=102.0)
    assert counts()[2] == {"saved_empty": 1}


def test_unknown_preview_preserves_zero_then_nonzero_wins(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    with as_account():
        issue(job(1), 100.0)
        report_ai._observe_report_ai_lifecycle(job(1, summary=None), now=101.0)
        report_ai._observe_report_ai_lifecycle(job(1, summary="неоднозначно"), now=102.0)
        report_ai._observe_report_ai_lifecycle(job(1, summary=NONZERO), now=103.0)
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=104.0)
    assert counts()[2] == {"preview_changed": 1}


def test_first_outcome_wins_and_eviction_counts_abandoned(monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: clock[0])
    monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 1)
    with as_account():
        issue(job(1), 100.0)
        report_ai._match_recreated_report_ai_job(job(2))
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=101.0)
        issue(job(3), 101.0)
        report_ai._observe_report_ai_lifecycle(job(4), now=102.0)
        report_ai._cleanup_report_ai_queue_observations(102.0)
    assert counts()[2] == {"recreated": 1, "abandoned_wait": 1}


def test_finalized_capacity_eviction_allows_local_reissue(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 1)
    with as_account():
        issue(job(1), 100.0)
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=100.0)
        report_ai._observe_report_ai_lifecycle(job(2, "saved", None), now=100.0)
        issue(job(1), 100.0)
    assert counts()[:2] == (2, 2)
    assert counts()[2] == {"saved_empty": 1}


@pytest.mark.parametrize("evict", [False, True])
def test_guided_lifecycle_expiry_or_eviction_preserves_old_terminal_counter(monkeypatch, evict):
    clock = [100.0]
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: clock[0])
    if evict:
        monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 1)
    with as_account():
        issue(job(1), clock[0])
        if evict:
            clock[0] = 101.0
            report_ai._observe_report_ai_lifecycle(job(2), now=clock[0])
        else:
            clock[0] = 3701.0
            report_ai._cleanup_report_ai_queue_observations(clock[0])
        report_ai._observe_report_ai_lifecycle(job(1, "saved", None), now=clock[0])
    assert counts()[2] == {"abandoned_wait": 1}
    assert metrics.snapshot_service_metrics()["report_ai_job_terminal_outcomes_total"] == {
        "abandoned_wait": 1, "saved": 1,
    }


@pytest.mark.parametrize("evict_in_cleanup", [False, True])
def test_unresolved_guidance_finalized_eviction_counts_abandoned(monkeypatch, evict_in_cleanup):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    with as_account():
        issue(job(1), 100.0)
        report_ai._observe_report_ai_lifecycle(job(1, "failed", None), now=101.0)
        assert counts()[2] == {}
        if evict_in_cleanup:
            monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 0)
            report_ai._cleanup_report_ai_queue_observations(102.0)
        else:
            monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 1)
            report_ai._observe_report_ai_lifecycle(job(2, "failed", None), now=102.0)
    assert counts()[2] == {"abandoned_wait": 1}


@pytest.mark.asyncio
@respx.mock
async def test_mcp_create_get_wait_guidance_text_and_metrics():
    billing_mock()
    body = {"data": {"job": job(373)}}
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(return_value=httpx.Response(201, json=body))
    respx.get(f"{BASE}/rest/api/report-ai-job/373").mock(return_value=httpx.Response(200, json=body))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        created = await mcp.call_tool("create_report_ai_job", {"intent_text": "Карты за январь 1900"})
        read = await mcp.call_tool("get_report_ai_job", {"job_id": 373})
        waited = await mcp.call_tool("get_report_ai_job", {"job_id": 373, "wait_seconds": 1})
    for result in (created, read, waited):
        steps = " ".join(result.structured_content["data"]["job"]["mcp_empty_preview_guidance"]["steps"])
        for phrase in ("названию клиники", "клиента", "только период", "по одному", "не живые данные", "полноценную проверку отчётом", "Не отвечайте пользователю по превью"):
            assert phrase in steps
    assert counts()[:2] == (3, 1)
    rendered = metrics.render_prometheus_metrics()
    assert 'vetmanager_report_ai_empty_preview_guidance_issued_total 3' in rendered
    assert 'vetmanager_report_ai_empty_preview_guidance_jobs_total 1' in rendered
    for line in rendered.splitlines():
        if line.startswith('vetmanager_report_ai_empty_preview_guidance_') and not line.startswith('#'):
            assert '373' not in line and 'Карты' not in line
            if '{' in line:
                assert line.split('{', 1)[1].startswith('outcome="')
    metrics.reset_service_metrics()
    assert metrics.snapshot_service_metrics()["report_ai_empty_preview_guidance_issued_total"] == 0


def test_no_guidance_for_saved_nonzero_ambiguous():
    with as_account():
        for i, item in enumerate((job(1, "saved"), job(2, summary=NONZERO), job(3, summary="0"))):
            report_ai._issued_empty_preview_guidance(report_ai._annotate_report_ai_workarounds({"data": {"job": item}}))
    assert counts()[:2] == (0, 0)


def test_closed_outcome_labels():
    with pytest.raises(ValueError):
        metrics.record_report_ai_empty_preview_outcome(outcome="job_id=123")
    assert "job_id=123" not in metrics.render_prometheus_metrics()


def test_unknown_account_never_matches_recreate(monkeypatch):
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 100.0)
    credentials = make_runtime_credentials("example", "test", account_id=None, connection_id=1)
    with use_runtime_credentials(credentials):
        issue(job(1), 100.0)
        report_ai._match_recreated_report_ai_job(job(2))
    assert counts()[2] == {}


@pytest.mark.asyncio
@respx.mock
async def test_mcp_new_create_attributes_prior_guided_job():
    billing_mock()
    first = {"data": {"job": job(373)}}
    second = {"data": {"job": job(374, "queued", None)}}
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(side_effect=[
        httpx.Response(201, json=first), httpx.Response(201, json=second),
    ])
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool("create_report_ai_job", {"intent_text": "Карты за январь 1900"})
        await mcp.call_tool("create_report_ai_job", {"intent_text": "Карты за февраль 1900"})
    assert counts()[2] == {"recreated": 1}
    assert metrics.snapshot_service_metrics()["report_ai_job_terminal_outcomes_total"] == {}


@pytest.mark.asyncio
@respx.mock
async def test_mcp_deduplicated_data_flag_does_not_attribute_recreated():
    billing_mock()
    first = {"data": {"job": job(373)}}
    second = {"data": {"job": job(374, "queued", None), "is_deduplicated": True}}
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(side_effect=[
        httpx.Response(201, json=first), httpx.Response(200, json=second),
    ])
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await mcp.call_tool("create_report_ai_job", {"intent_text": "Карты за январь 1900"})
        await mcp.call_tool("create_report_ai_job", {"intent_text": "Карты за февраль 1900"})
    assert counts()[2] == {}
