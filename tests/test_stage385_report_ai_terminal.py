"""A Report AI terminal event belongs to one logical job across slots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

import fakeredis
import httpx
import pytest
import respx

import shared_metric_counters
import tools.report_ai as report_ai
from runtime_auth import use_runtime_credentials
from shared_metric_counters import RedisMetricCounters
from tests.runtime_factories import make_runtime_credentials
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from server import mcp


def test_terminal_outcome_is_atomic_across_two_slot_observers(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    selected = [workers[0]]
    monkeypatch.setenv("REDIS_URL", "redis://shared.test/0")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: selected[0])
    job = {"id": 385001, "status": "saved"}

    report_ai._observe_report_ai_lifecycle(job, now=10.0)
    report_ai._reset_report_ai_queue_observations()  # independent slot memory
    selected[0] = workers[1]
    report_ai._observe_report_ai_lifecycle(job, now=11.0)

    assert workers[0].snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}
    assert workers[1].snapshot()["report_ai_job_duration_seconds"]["saved"]["count"] == 1
    assert workers[0].snapshot()["report_ai_job_stage_duration_seconds"]["saved"]["count"] == 1
    assert all(b"385001" not in key for key in server.dbs[0])


def test_concurrent_terminal_claim_is_one_counter_and_one_duration():
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(3)]
    with ThreadPoolExecutor(max_workers=3) as pool:
        claimed = list(pool.map(
            lambda worker: worker.claim_report_ai_terminal("a" * 64, "failed", 7.0, 3600),
            workers,
        ))
    assert claimed.count(True) == 1
    assert workers[0].snapshot()["report_ai_job_terminal_outcomes_total"] == {"failed": 1}
    assert workers[1].snapshot()["report_ai_job_duration_seconds"]["failed"] == {
        "count": 1, "sum_seconds": 7.0, "max_seconds": 7.0,
    }


def test_same_clinic_job_on_different_connections_has_one_terminal(monkeypatch):
    server = fakeredis.FakeServer()
    backend = RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job = {"id": 385002, "status": "saved"}
    for connection_id in (1, 2):
        credentials = make_runtime_credentials("clinic-one", "test-key",
                                               account_id=1, connection_id=connection_id)
        with use_runtime_credentials(credentials):
            report_ai._observe_report_ai_lifecycle(job, now=10.0 + connection_id)
        report_ai._reset_report_ai_queue_observations()
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}
    other_clinic = make_runtime_credentials("clinic-two", "test-key",
                                            account_id=1, connection_id=3)
    with use_runtime_credentials(other_clinic):
        report_ai._observe_report_ai_lifecycle(job, now=13.0)
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 2}


@pytest.mark.asyncio
async def test_slow_terminal_claim_does_not_block_event_loop(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    real_claim = backend.observe_report_ai_lifecycle
    calls = []

    def slow_claim(*args, **kwargs):
        calls.append(1)
        time.sleep(.2)
        return real_claim(*args, **kwargs)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(backend, "observe_report_ai_lifecycle", slow_claim)
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    loop = asyncio.get_running_loop()
    started = loop.time()
    ticks = []
    loop.call_later(.01, lambda: ticks.append(loop.time() - started))
    report_ai._observe_report_ai_lifecycle({"id": 385003, "status": "saved"}, now=10.0)
    await asyncio.sleep(.03)
    assert calls and ticks and ticks[0] < .1
    assert await shared_metric_counters.wait_pending()


@pytest.mark.asyncio
@respx.mock
async def test_slow_recreated_observation_does_not_block_event_loop(monkeypatch):
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job").mock(return_value=httpx.Response(
        201, json={"success": True, "data": {"job": {"id": 385017, "status": "queued"}}}))
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    real_resolve = backend.resolve_recreated_report_ai_guidance
    entered = []
    ticks = []
    loop = asyncio.get_running_loop()

    def slow_resolve(*args, **kwargs):
        entered.append(loop.time())
        loop.call_soon_threadsafe(lambda: ticks.append(loop.time()))
        time.sleep(.2)
        return real_resolve(*args, **kwargs)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(backend, "resolve_recreated_report_ai_guidance", slow_resolve)
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {
            "intent_text": "Количество клиентов за январь 1900 года"})
    assert result.structured_content["data"]["job"]["id"] == 385017
    assert entered and ticks and ticks[0] - entered[0] < .1


@pytest.mark.asyncio
@respx.mock
async def test_slow_reject_observation_does_not_block_status_request(monkeypatch):
    billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/385018").mock(return_value=httpx.Response(
        200, json={"success": True, "data": {"job": {
            "id": 385018, "status": "needs_confirmation", "candidates": []}}}))
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    real_pending = backend.report_ai_reject_pending
    loop = asyncio.get_running_loop()
    entered = []
    ticks = []

    def slow_pending(*args, **kwargs):
        entered.append(loop.time())
        loop.call_soon_threadsafe(lambda: ticks.append(loop.time()))
        time.sleep(.2)
        return real_pending(*args, **kwargs)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(backend, "report_ai_reject_pending", slow_pending)
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job", {"job_id": 385018})
    assert result.structured_content["data"]["job"]["id"] == 385018
    assert entered and ticks and ticks[0] - entered[0] < .1


def test_late_terminal_poll_keeps_prior_stage_observation(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job_id = 385004
    report_ai._observe_report_ai_lifecycle({"id": job_id, "status": "queued"}, now=1.0)
    slot_a = report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS.copy()
    report_ai._reset_report_ai_queue_observations()
    report_ai._observe_report_ai_lifecycle({"id": job_id, "status": "saved"}, now=2.0)
    report_ai._reset_report_ai_queue_observations()
    report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS.update(slot_a)
    report_ai._observe_report_ai_lifecycle({"id": job_id, "status": "saved"}, now=3.0)
    snapshot = backend.snapshot()
    assert snapshot["report_ai_job_terminal_outcomes_total"] == {"saved": 1}
    assert snapshot["report_ai_job_stage_duration_seconds"]["queued"]["count"] == 1
    assert snapshot["report_ai_job_transitions_total"] == {"queued|saved": 1}


def test_duplicate_terminal_poll_refreshes_shared_tombstone():
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(client)
    digest = "b" * 64
    assert backend.claim_report_ai_terminal(digest, "saved", 1.0, 3600)
    tombstone = shared_metric_counters.REPORT_AI_TERMINAL_KEY_PREFIX + digest
    assert client.pexpire(tombstone, 100)
    assert not backend.claim_report_ai_terminal(digest, "saved", 1.0, 3600)
    assert client.ttl(tombstone) >= 3590
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}


def test_same_slot_finalized_poll_refreshes_shared_tombstone(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(client)
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job = {"id": 385005, "status": "saved"}
    report_ai._observe_report_ai_lifecycle(job, now=10.0)
    tombstone = next(key for key in client.scan_iter()
                     if key.startswith(shared_metric_counters.REPORT_AI_TERMINAL_KEY_PREFIX))
    client.pexpire(tombstone, 100)
    report_ai._observe_report_ai_lifecycle(job, now=11.0)
    assert client.ttl(tombstone) >= 3590
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}


def test_failed_lifecycle_write_cannot_create_uncounted_tombstone(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(client)
    real_observe = backend.observe_report_ai_lifecycle
    calls = [0]

    def fail_once(*args, **kwargs):
        calls[0] += 1
        if calls[0] == 1:
            raise ConnectionError("Redis unavailable")
        return real_observe(*args, **kwargs)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(backend, "observe_report_ai_lifecycle", fail_once)
    job = {"id": 385006, "status": "saved"}
    report_ai._observe_report_ai_lifecycle(job, now=10.0)
    report_ai._observe_report_ai_lifecycle(job, now=11.0)  # local finalized refresh
    report_ai._reset_report_ai_queue_observations()  # another slot after Redis recovers
    report_ai._observe_report_ai_lifecycle(job, now=12.0)
    assert calls[0] == 3
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}


def test_expired_job_on_two_slots_has_one_abandoned_outcome(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job = {"id": 385007, "status": "queued"}
    report_ai._observe_report_ai_lifecycle(job, now=1.0)
    first_slot = report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS.copy()
    report_ai._reset_report_ai_queue_observations()
    report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS.update(first_slot)
    report_ai._cleanup_report_ai_queue_observations(3602.0)
    assert backend.cleanup_report_ai_lifecycle(3602.0, 3600) == 1
    report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS.update(first_slot)
    report_ai._cleanup_report_ai_queue_observations(3602.0)
    assert backend.cleanup_report_ai_lifecycle(3602.0, 3600) == 0
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"abandoned_wait": 1}
    assert backend.snapshot()["report_ai_job_stage_duration_seconds"]["queued"]["count"] == 1


def test_shared_lifecycle_transition_survives_slot_switch(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job_id = 385008
    report_ai._observe_report_ai_lifecycle({"id": job_id, "status": "queued"}, now=1.0)
    report_ai._reset_report_ai_queue_observations()
    report_ai._observe_report_ai_lifecycle({"id": job_id, "status": "saved"}, now=6.0)
    snapshot = backend.snapshot()
    assert snapshot["report_ai_job_transitions_total"] == {"queued|saved": 1}
    assert snapshot["report_ai_job_stage_duration_seconds"]["queued"]["sum_seconds"] == 5.0
    assert snapshot["report_ai_job_duration_seconds"]["saved"]["sum_seconds"] == 5.0


def test_shared_lifecycle_evicts_oldest_before_dropping_it():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    for number in range(3):
        backend.observe_report_ai_lifecycle(f"{number:064x}", "queued", float(number), 3600)
    backend.cleanup_report_ai_lifecycle(3.0, 3600, max_entries=2)
    snapshot = backend.snapshot()
    assert snapshot["report_ai_job_terminal_outcomes_total"] == {"abandoned_wait": 1}
    assert snapshot["report_ai_job_stage_duration_seconds"]["queued"]["count"] == 1
    assert backend._redis.zcard(shared_metric_counters.REPORT_AI_EXPIRY_INDEX) == 2


def test_eviction_skips_job_refreshed_after_selection():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "9" * 64
    backend.observe_report_ai_lifecycle(digest, "queued", 1.0, 3600)
    backend.observe_report_ai_lifecycle(digest, "queued", 2.0, 3600)
    backend.observe_report_ai_lifecycle(
        digest, "abandoned_wait", 3.0, 3600, expiry_only=True,
        force=True, expected_expiry_at=3601.0)
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {}


def test_shared_failed_job_keeps_bounded_outcome_code(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    report_ai._observe_report_ai_lifecycle(
        {"id": 385012, "status": "failed", "error_code": "PREVIEW_FAILED"}, now=1.0)
    assert backend.snapshot()["report_ai_outcomes_by_code_total"] == {
        "status|PREVIEW_FAILED": 1}


def test_concurrent_shared_expiry_has_one_terminal_and_stage_duration():
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(3)]
    digest = "c" * 64
    workers[0].observe_report_ai_lifecycle(digest, "queued", 1.0, 3600)
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda worker: worker.cleanup_report_ai_lifecycle(3602.0, 3600), workers))
    snapshot = workers[0].snapshot()
    assert snapshot["report_ai_job_terminal_outcomes_total"] == {"abandoned_wait": 1}
    assert snapshot["report_ai_job_stage_duration_seconds"]["queued"]["count"] == 1
    assert "abandoned_wait" not in snapshot["report_ai_job_stage_duration_seconds"]


def test_guidance_first_job_and_outcome_are_shared_across_slots():
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    digest = "d" * 64
    workers[0].issue_report_ai_guidance(digest, 1.0, 3600)
    workers[1].issue_report_ai_guidance(digest, 2.0, 3600)
    workers[1].resolve_report_ai_guidance(digest, "saved_empty", 3.0, 3600)
    workers[0].resolve_report_ai_guidance(digest, "saved_empty", 4.0, 3600)
    snapshot = workers[0].snapshot()
    assert snapshot["report_ai_empty_preview_guidance_issued_total"] == 2
    assert snapshot["report_ai_empty_preview_guidance_jobs_total"] == 1
    assert snapshot["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_guidance_resolution_before_delayed_issue_is_saved():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "a" * 64
    backend.resolve_report_ai_guidance(digest, "saved_empty", 2.0, 3600)
    backend.issue_report_ai_guidance(digest, 1.0, 3600)
    snapshot = backend.snapshot()
    assert snapshot["report_ai_empty_preview_guidance_jobs_total"] == 1
    assert snapshot["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_earlier_preview_change_is_not_future_guidance_outcome():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "2" * 64
    backend.resolve_report_ai_guidance(digest, "preview_changed", 1.0, 3600)
    backend.issue_report_ai_guidance(digest, 2.0, 3600)
    backend.resolve_report_ai_guidance(digest, "saved_empty", 3.0, 3600)
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_delayed_guidance_issue_cannot_shorten_shared_expiry():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "e" * 64
    backend.issue_report_ai_guidance(digest, 20.0, 3600)
    backend.issue_report_ai_guidance(digest, 10.0, 3600)
    backend.cleanup_report_ai_guidance(3611.0, 3600)
    backend.resolve_report_ai_guidance(digest, "saved_empty", 3612.0, 3600)
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_shared_guidance_survives_local_finalized_eviction(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(report_ai, "REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES", 1)
    digest = "f" * 64
    backend.issue_report_ai_guidance(digest, 1.0, 3600)
    backend.issue_report_ai_guidance(digest, 1000.0, 3600)
    report_ai._remember_finalized_report_ai_job(
        (1, 1, 385061), now=1.0,
        observation={"guidance_issued_at": 1.0, "guidance_digest": digest},
    )
    report_ai._remember_finalized_report_ai_job((1, 1, 385062), now=2.0)
    backend.resolve_report_ai_guidance(digest, "recreated", 1001.0, 3600)
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {"recreated": 1}


def test_local_guidance_expiry_does_not_override_shared_refresh(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    digest = "b" * 64
    backend.issue_report_ai_guidance(digest, 1.0, 3600)
    backend.issue_report_ai_guidance(digest, 1000.0, 3600)
    key = (1, 1, 385055)
    report_ai._REPORT_AI_LIFECYCLE_OBSERVATIONS[key] = {
        "last_seen": 1.0, "guidance_issued_at": 1.0,
        "guidance_digest": digest,
    }
    report_ai._cleanup_report_ai_queue_observations(3602.0)
    backend.resolve_report_ai_guidance(digest, "saved_empty", 3603.0, 3600)
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_guidance_issued_on_two_slots_resolves_after_handoff(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    ready = {"id": 385009, "status": "ready_to_save",
             "preview_summary": "Превью: 0 строк",
             "mcp_empty_preview_guidance": {"code": "report_ai_empty_preview"}}
    report_ai._issued_empty_preview_guidance({"data": {"job": ready}})
    report_ai._reset_report_ai_queue_observations()
    report_ai._issued_empty_preview_guidance({"data": {"job": ready}})
    report_ai._reset_report_ai_queue_observations()
    report_ai._observe_report_ai_lifecycle({"id": 385009, "status": "saved"}, now=20.0)
    snapshot = backend.snapshot()
    assert snapshot["report_ai_empty_preview_guidance_jobs_total"] == 1
    assert snapshot["report_ai_empty_preview_guidance_issued_total"] == 2
    assert snapshot["report_ai_empty_preview_guidance_outcomes_total"] == {"saved_empty": 1}


def test_guidance_idle_expiry_is_finalized_once():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "e" * 64
    backend.issue_report_ai_guidance(digest, 1.0, 3600)
    assert backend.cleanup_report_ai_guidance(3602.0, 3600) == 1
    assert backend.cleanup_report_ai_guidance(3602.0, 3600) == 0
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {
        "abandoned_wait": 1}


def test_guidance_overflow_finalizes_oldest():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    for number in range(3):
        backend.issue_report_ai_guidance(f"{number:064x}", float(number), 3600)
    backend.cleanup_report_ai_guidance(3.0, 3600, max_entries=2)
    assert backend.snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {
        "abandoned_wait": 1}


def test_export_terminal_and_expiry_outcomes_are_shared():
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    digest = "f" * 64
    workers[0].remember_report_ai_export(digest, 1.0, 3600)
    assert workers[1].complete_report_ai_export(digest, "success", 6.0, 3600)
    assert not workers[0].complete_report_ai_export(digest, "success", 7.0, 3600)
    snapshot = workers[0].snapshot()
    assert snapshot["report_ai_exports_total"]["poll|success"] == 1
    assert snapshot["report_ai_export_duration_seconds"]["success"]["sum_seconds"] == 5.0
    other = "a" * 64
    workers[0].remember_report_ai_export(other, 10.0, 3600)
    assert workers[1].cleanup_report_ai_exports(3611.0, 3600) == 1
    assert workers[0].cleanup_report_ai_exports(3611.0, 3600) == 0
    assert workers[0].snapshot()["report_ai_exports_total"]["start|abandoned_wait"] == 1


def test_export_overflow_finalizes_oldest():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    for number in range(3):
        backend.remember_report_ai_export(f"{number:064x}", float(number), 3600)
    backend.cleanup_report_ai_exports(3.0, 3600, max_entries=2)
    assert backend.snapshot()["report_ai_exports_total"]["start|abandoned_wait"] == 1


def test_export_completion_from_another_slot_is_one_outcome(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    report_ai._remember_report_ai_export(385010)
    report_ai._reset_report_ai_queue_observations()
    report_ai._complete_report_ai_export(385010, outcome="success")
    report_ai._complete_report_ai_export(385010, outcome="success")
    assert backend.snapshot()["report_ai_exports_total"]["poll|success"] == 1
    assert backend.snapshot()["report_ai_export_duration_seconds"]["success"]["count"] == 1


def test_queue_age_survives_slot_switch_without_upstream_timestamp():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "1" * 64
    assert backend.observe_report_ai_queue(digest, True, 1.0, 3600) == 0
    assert backend.observe_report_ai_queue(digest, True, 51.0, 3600) == 50
    backend.observe_report_ai_queue(digest, False, 52.0, 3600)
    assert backend.observe_report_ai_queue(digest, True, 53.0, 3600) == 0


def test_export_poll_before_async_start_preserves_poll_state():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "2" * 64
    backend.mark_report_ai_export_poll(digest, 2.0, 3600)
    backend.remember_report_ai_export(digest, 3.0, 3600)
    backend.cleanup_report_ai_exports(3604.0, 3600)
    assert backend.snapshot()["report_ai_exports_total"]["poll|abandoned_wait"] == 1


def test_export_poll_before_start_preserves_true_start_duration():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "c" * 64
    backend.mark_report_ai_export_poll(digest, 2.0, 3600)
    backend.remember_report_ai_export(digest, 1.0, 3600)
    backend.complete_report_ai_export(digest, "success", 6.0, 3600)
    assert backend.snapshot()["report_ai_export_duration_seconds"]["success"]["sum_seconds"] == 5.0


def test_delayed_export_poll_cannot_shorten_shared_expiry():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "1" * 64
    backend.remember_report_ai_export(digest, 1.0, 3600)
    backend.mark_report_ai_export_poll(digest, 20.0, 3600)
    backend.mark_report_ai_export_poll(digest, 10.0, 3600)
    backend.cleanup_report_ai_exports(3611.0, 3600)
    backend.complete_report_ai_export(digest, "success", 3612.0, 3600)
    assert backend.snapshot()["report_ai_exports_total"]["poll|success"] == 1


def test_old_slot_update_cannot_move_shared_stage_backwards():
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    digest = "d" * 64
    backend.observe_report_ai_lifecycle(digest, "queued", 1.0, 3600)
    backend.observe_report_ai_lifecycle(digest, "preview", 3.0, 3600)
    backend.observe_report_ai_lifecycle(digest, "queued", 2.0, 3600)
    backend.observe_report_ai_lifecycle(digest, "saved", 4.0, 3600)
    assert backend.snapshot()["report_ai_job_transitions_total"] == {
        "queued|preview": 1, "preview|saved": 1,
    }


@pytest.mark.asyncio
async def test_queue_diagnostics_read_shared_age_after_slot_switch(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    async def no_upstream_age(_job):
        return None
    monkeypatch.setattr(report_ai, "_upstream_job_age_seconds", no_upstream_age)
    job = {"id": 385011, "status": "queued"}
    await report_ai._annotate_report_ai_queue_diagnostics({"data": {"job": job}}, now=1.0)
    report_ai._reset_report_ai_queue_observations()
    payload = await report_ai._annotate_report_ai_queue_diagnostics(
        {"data": {"job": job}}, now=51.0)
    assert payload["data"]["job"]["mcp_queue_diagnostics"]["observed_queued_age_seconds"] == 50


def test_reject_pending_survives_slot_switch(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job = {"id": 385012, "status": "needs_confirmation"}
    report_ai._remember_reject_pending(job)
    report_ai._reset_report_ai_queue_observations()
    assert report_ai._is_reject_pending(job)
    assert not report_ai._is_reject_pending({**job, "status": "saved"})
    report_ai._reset_report_ai_queue_observations()
    assert not report_ai._is_reject_pending(job)


def test_reject_pending_recovers_shared_marker_after_redis_returns(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    selected = [workers[0]]
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: selected[0])
    job = {"id": 385017, "status": "needs_confirmation"}

    def unavailable(*_args, **_kwargs):
        raise OSError("Redis unavailable during reject")

    monkeypatch.setattr(workers[0], "mark_report_ai_reject_pending", unavailable)
    report_ai._remember_reject_pending(job)
    selected[0] = workers[1]
    assert report_ai._is_reject_pending(job)
    report_ai._reset_report_ai_queue_observations()
    assert report_ai._is_reject_pending(job)


def test_export_wait_age_survives_slot_switch(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 10.0)
    report_ai._remember_report_ai_export(385013)
    report_ai._reset_report_ai_queue_observations()
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 50.0)
    assert report_ai._report_ai_export_observed_wait_seconds(385013) == 40


def test_queue_observation_starts_on_create_before_diagnostic_poll(monkeypatch):
    backend = RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    job = {"id": 385014, "status": "queued"}
    report_ai._observe_report_ai_queue(job, now=1.0)
    report_ai._reset_report_ai_queue_observations()
    key = report_ai._report_ai_queue_observation_key(job)
    assert backend.observe_report_ai_queue(report_ai._report_ai_terminal_digest(key),
                                           True, 51.0, 3600) == 50


def test_guidance_recreated_after_slot_switch(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    selected = [workers[0]]
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: selected[0])
    credentials = make_runtime_credentials("clinic-one", "test-key", account_id=7,
                                           connection_id=1)
    with use_runtime_credentials(credentials):
        old = {"id": 385015, "status": "ready_to_save",
               "mcp_empty_preview_guidance": {"code": "report_ai_empty_preview"}}
        report_ai._issued_empty_preview_guidance({"data": {"job": old}})
        report_ai._reset_report_ai_queue_observations()
        selected[0] = workers[1]
        report_ai._match_recreated_report_ai_job({"id": 385016}, is_deduplicated=False)
    assert workers[0].snapshot()["report_ai_empty_preview_guidance_outcomes_total"] == {
        "recreated": 1}
    assert all(b"385015" not in key for key in server.dbs[0])


def test_guidance_account_index_is_bounded():
    server = fakeredis.FakeServer()
    backend = RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
    for number in range(3):
        backend.issue_report_ai_guidance(
            f"{number:064x}", float(number), 3600,
            account_digest="a" * 64, max_account_entries=2)
    key = shared_metric_counters.REPORT_AI_GUIDANCE_ACCOUNT_PREFIX + "a" * 64
    assert backend._redis.zcard(key) == 2
    assert backend._redis.zrange(key, 0, -1) == [f"{number:064x}" for number in (1, 2)]


def test_resolved_guidance_leaves_account_index_immediately():
    server = fakeredis.FakeServer()
    backend = RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
    account = "a" * 64
    digest = "b" * 64
    backend.issue_report_ai_guidance(digest, 10.0, 3600, account_digest=account)
    key = shared_metric_counters.REPORT_AI_GUIDANCE_ACCOUNT_PREFIX + account
    assert backend._redis.zcard(key) == 1
    assert backend.resolve_report_ai_guidance(digest, "saved_empty", 11.0, 3600)
    assert backend._redis.zcard(key) == 0
