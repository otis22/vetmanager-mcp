"""A Report AI terminal event belongs to one logical job across slots."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import time

import fakeredis
import pytest

import shared_metric_counters
import tools.report_ai as report_ai
from runtime_auth import use_runtime_credentials
from shared_metric_counters import RedisMetricCounters
from tests.runtime_factories import make_runtime_credentials


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
    real_claim = backend.claim_report_ai_terminal

    def slow_claim(*args):
        time.sleep(.2)
        return real_claim(*args)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(backend, "claim_report_ai_terminal", slow_claim)
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    loop = asyncio.get_running_loop()
    started = loop.time()
    ticks = []
    loop.call_later(.01, lambda: ticks.append(loop.time() - started))
    report_ai._observe_report_ai_lifecycle({"id": 385003, "status": "saved"}, now=10.0)
    await asyncio.sleep(.03)
    assert ticks and ticks[0] < .1
    assert await shared_metric_counters.wait_pending()


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


def test_failed_claim_cannot_create_uncounted_tombstone_on_later_poll(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisMetricCounters(client)
    real_claim = backend.claim_report_ai_terminal
    calls = [0]

    def fail_once(*args):
        calls[0] += 1
        if calls[0] == 1:
            raise ConnectionError("Redis unavailable")
        return real_claim(*args)

    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-report-ai-secret")
    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: backend)
    monkeypatch.setattr(backend, "claim_report_ai_terminal", fail_once)
    job = {"id": 385006, "status": "saved"}
    report_ai._observe_report_ai_lifecycle(job, now=10.0)
    report_ai._observe_report_ai_lifecycle(job, now=11.0)  # local finalized refresh
    report_ai._reset_report_ai_queue_observations()  # another slot after Redis recovers
    report_ai._observe_report_ai_lifecycle(job, now=12.0)
    assert backend.snapshot()["report_ai_job_terminal_outcomes_total"] == {"saved": 1}
