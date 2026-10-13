"""Stage 385.2c1: counters from separate workers have one Redis value."""

import asyncio
import time
import threading

import fakeredis
import httpx
import pytest
import re

import service_metrics
from shared_metric_counters import (
    RedisMetricCounters, SHARED_COUNTER_FAMILIES, require_shared_metrics_config,
    verify_shared_metrics_startup,
)
from request_cache import InMemoryTaggedCache
from server import mcp


def test_every_process_counter_has_a_shared_owner():
    exported = {name for name in service_metrics.snapshot_service_metrics()
                if name.endswith("_total")}
    assert exported <= SHARED_COUNTER_FAMILIES


def test_shared_metric_help_does_not_claim_single_process_scope():
    help_lines = [line for line in service_metrics.render_prometheus_metrics().splitlines()
                  if line.startswith("# HELP ")]
    assert not [line for line in help_lines
                if re.search(r"process.local|in this process", line, re.IGNORECASE)]


def test_three_slots_cannot_start_with_process_local_metrics(monkeypatch):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValueError, match="REDIS_URL"):
        require_shared_metrics_config()


@pytest.mark.asyncio
async def test_three_slots_cannot_report_ready_with_unreachable_redis(monkeypatch):
    class BrokenBackend:
        def ping(self):
            raise ConnectionError("redis down")

    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid:6379/0")
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend",
                        lambda: BrokenBackend())
    with pytest.raises(Exception, match="Shared metrics"):
        await verify_shared_metrics_startup()


@pytest.mark.asyncio
async def test_slow_metric_backend_does_not_block_request_event_loop(monkeypatch):
    class SlowBackend:
        def increment(self, *_args):
            time.sleep(.2)

        def observe(self, *_args):
            time.sleep(.2)

    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend",
                        lambda: SlowBackend())
    tick = asyncio.create_task(asyncio.sleep(.01))
    started = time.monotonic()
    service_metrics.record_tool_call(endpoint="/rest/api/client#list", method="GET",
                                     outcome="success", duration_seconds=.01)
    await tick
    assert time.monotonic() - started < .1
    assert await service_metrics.shared_metric_counters.wait_pending()


@pytest.mark.asyncio
async def test_metrics_scrape_timeout_does_not_cancel_queued_delivery():
    gate = threading.Event()
    called = []
    first = service_metrics.shared_metric_counters.dispatch(lambda: gate.wait(.5))
    second = service_metrics.shared_metric_counters.dispatch(lambda: called.append("delivered"))
    try:
        assert not await service_metrics.shared_metric_counters.wait_pending(.01)
        gate.set()
        await asyncio.wrap_future(first)
        await asyncio.wrap_future(second)
        assert called == ["delivered"]
    finally:
        gate.set()


def test_http_tool_auth_and_upstream_counters_are_shared(monkeypatch):
    server = fakeredis.FakeServer()
    worker_a = RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
    worker_b = RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
    service_metrics.reset_service_metrics()

    for backend in (worker_a, worker_b, worker_a):
        monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
        service_metrics.record_http_request(route="/mcp", method="POST", status_code=200,
                                            duration_seconds=.01)
        service_metrics.record_tool_call(endpoint="/rest/api/client#list", method="GET",
                                         outcome="success", duration_seconds=.01)
        service_metrics.record_auth_failure(source="bearer", reason="invalid_token")
        service_metrics.record_upstream_request(target="vetmanager_api", status="success",
                                                duration_seconds=.01)
    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: worker_b)
    snapshot = service_metrics.snapshot_service_metrics()
    assert snapshot["http_requests_total"]["/mcp|POST|200"] == 3
    assert snapshot["tool_calls_total"]["/rest/api/client#list|GET|success"] == 3
    assert snapshot["auth_failures_total"]["bearer|invalid_token"] == 3
    assert snapshot["upstream_requests_total"]["vetmanager_api|success"] == 3
    assert worker_a.snapshot() == worker_b.snapshot()


def test_all_remaining_counter_recorders_share_their_values(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    service_metrics.reset_service_metrics()
    events = [
        ("sentry_delivery_lost_total", "dns", lambda: service_metrics.record_sentry_delivery_lost("dns")),
        ("sentry_delivery_accepted_total", "", lambda: service_metrics.record_sentry_delivery_accepted(1)),
        ("known_issue_lookups_total", "get_clients|no_match|failure", lambda: service_metrics.record_known_issue_lookup(tool_name="get_clients", outcome="no_match")),
        ("prompt_requests_total", "list|help", lambda: service_metrics.record_prompt_request(method="list", prompt="help", allowed_names=frozenset({"help"}))),
        ("token_expiry_notice_issued_total", "1d", lambda: service_metrics.record_token_expiry_notice_issued(1)),
        ("token_expiry_notice_skipped_total", "claim_recent", lambda: service_metrics.record_token_expiry_notice_skipped("claim_recent")),
        ("token_preset_issued_total", "read_only", lambda: service_metrics.record_token_preset_issued("read_only")),
        ("placeholder_argument_rejections_total", "get_clients", lambda: service_metrics.record_placeholder_argument_rejection("get_clients")),
        ("rate_limit_backend_degraded_total", "unavailable", lambda: service_metrics.record_rate_limit_backend_degraded("unavailable")),
        ("sanitizer_failures_total", "", service_metrics.record_sanitizer_failure),
        ("rest_unmapped_read_total", "", service_metrics.record_rest_unmapped_read),
        ("report_export_download_total", "success", lambda: service_metrics.record_report_export_download(outcome="success")),
        ("report_export_serve_total", "success", lambda: service_metrics.record_report_export_serve(outcome="success")),
        ("report_ai_long_queued_polls_total", "", service_metrics.record_report_ai_long_queued_poll),
        ("report_ai_stage_stall_polls_total", "", service_metrics.record_report_ai_stage_stall_poll),
        ("report_ai_jobs_total", "success", lambda: service_metrics.record_report_ai_job_created(outcome="success")),
        ("report_ai_save_attempts_total", "success", lambda: service_metrics.record_report_ai_save_attempt(outcome="success")),
        ("report_ai_job_transitions_total", "queued|running", lambda: service_metrics.record_report_ai_job_transition(from_stage="queued", to_stage="running")),
        ("report_ai_job_terminal_outcomes_total", "completed", lambda: service_metrics.record_report_ai_job_terminal_outcome(outcome="completed", duration_seconds=1)),
        ("report_ai_empty_preview_guidance_issued_total", "", lambda: service_metrics.record_report_ai_empty_preview_guidance(first=True)),
        ("report_ai_empty_preview_guidance_jobs_total", "", None),
        ("report_ai_empty_preview_guidance_outcomes_total", "recreated", lambda: service_metrics.record_report_ai_empty_preview_outcome(outcome="recreated")),
        ("report_ai_exports_total", "start|success", lambda: service_metrics.record_report_ai_export(operation="start", outcome="success")),
        ("report_ai_outcomes_by_code_total", "job|NOT_FOUND", lambda: service_metrics.record_report_ai_outcome_code(operation="job", code="NOT_FOUND")),
        ("business_events_total", "web_login_succeeded", lambda: service_metrics.record_business_event("web_login_succeeded")),
    ]
    for backend in workers:
        monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
        for _, _, emit in events:
            if emit is not None:
                emit()
    snapshot = service_metrics.snapshot_service_metrics()
    for family, key, _ in events:
        value = snapshot[family] if not key else snapshot[family][key]
        assert value == 2, family
    assert workers[0].snapshot() == workers[1].snapshot()


def test_latency_count_sum_and_max_are_shared_atomically(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    service_metrics.reset_service_metrics()
    for backend, duration in zip((workers[0], workers[1], workers[0]), (.01, .09, .03)):
        monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend", lambda: backend)
        service_metrics.record_tool_call(endpoint="/rest/api/client#list", method="GET",
                                         outcome="success", duration_seconds=duration)
    snapshot = service_metrics.snapshot_service_metrics()
    aggregate = snapshot["tool_call_latency_seconds"]["/rest/api/client#list|GET"]
    assert aggregate["count"] == 3
    assert abs(aggregate["sum_seconds"] - .13) < 1e-9
    assert aggregate["max_seconds"] == .09
    assert workers[0].snapshot()["tool_call_latency_seconds"]["/rest/api/client#list|GET"] == aggregate
    assert workers[0].snapshot() == workers[1].snapshot()


@pytest.mark.asyncio
async def test_cache_events_and_slot_entries_are_shared(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [RedisMetricCounters(fakeredis.FakeRedis(server=server, decode_responses=True))
               for _ in range(2)]
    caches = [InMemoryTaggedCache(max_entries=1) for _ in range(2)]
    for index, (worker, cache) in enumerate(zip(workers, caches)):
        monkeypatch.setattr("request_cache.shared_metric_counters.get_backend", lambda: worker)
        monkeypatch.setattr("request_cache._slot_identity", lambda: f"slot-{index}")
        assert await cache.get("missing") is None
        await cache.set("a", {"ok": True}, 60, ("a",))
        assert await cache.get("a") == {"ok": True}
        await cache.set("b", {"ok": True}, 60, ("b",))
        await cache.refresh_shared_gauge()
    assert await service_metrics.shared_metric_counters.wait_pending()
    assert workers[0].snapshot()["cache_entries"] == 2
    for index, (worker, cache) in enumerate(zip(workers, caches)):
        monkeypatch.setattr("request_cache.shared_metric_counters.get_backend", lambda: worker)
        monkeypatch.setattr("request_cache._slot_identity", lambda: f"slot-{index}")
        await cache.invalidate_tag("b")
        await cache.refresh_shared_gauge()
    assert await service_metrics.shared_metric_counters.wait_pending()
    snapshot = workers[0].snapshot()
    assert snapshot["cache_misses_total"] == 2
    assert snapshot["cache_hits_total"] == 2
    assert snapshot["cache_evictions_total"] == 2
    assert snapshot["cache_invalidations_total"] == 2
    assert snapshot["cache_entries"] == 0


@pytest.mark.asyncio
async def test_metrics_returns_503_when_shared_store_fails_after_a_tool_event(monkeypatch):
    class BrokenBackend:
        def increment(self, *_args):
            raise ConnectionError("redis down")

        def snapshot(self):
            raise ConnectionError("redis down")

    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend",
                        lambda: BrokenBackend())
    service_metrics.record_tool_call(endpoint="/rest/api/client#list", method="GET",
                                     outcome="success", duration_seconds=.01)
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        response = await client.get("/metrics")
    assert response.status_code == 503


@pytest.mark.asyncio
async def test_slow_metric_scrape_does_not_block_event_loop(monkeypatch):
    class SlowBackend:
        def snapshot(self):
            time.sleep(.2)
            return {}

        def increment(self, *_args):
            return None

        def observe(self, *_args):
            return None

    monkeypatch.setattr(service_metrics.shared_metric_counters, "get_backend",
                        lambda: SlowBackend())
    app = mcp.http_app(path="/mcp", transport="streamable-http")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://testserver") as client:
        tick = asyncio.create_task(asyncio.sleep(.01))
        started = time.monotonic()
        metrics = asyncio.create_task(client.get("/metrics"))
        await tick
        assert time.monotonic() - started < .1
        assert (await metrics).status_code == 200
