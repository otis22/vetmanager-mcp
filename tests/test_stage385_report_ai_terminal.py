"""A Report AI terminal event belongs to one logical job across slots."""

from concurrent.futures import ThreadPoolExecutor

import fakeredis

import shared_metric_counters
import tools.report_ai as report_ai
from shared_metric_counters import RedisMetricCounters


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
