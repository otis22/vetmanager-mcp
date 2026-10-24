"""Histogram buckets survive shared storage and label normalization."""

import asyncio

import fakeredis
import httpx
import pytest
import respx

import host_resolver
import service_metrics as metrics
import shared_metric_counters as shared


@pytest.mark.asyncio
async def test_cross_slot_buckets_and_legacy_reader(monkeypatch):
    server = fakeredis.FakeServer()
    workers = [shared.RedisMetricCounters(fakeredis.FakeRedis(
        server=server, decode_responses=True)) for _ in range(2)]
    metrics.reset_service_metrics()
    for backend, duration in zip(workers, (.2, 25.)):
        monkeypatch.setattr(shared, "get_backend", lambda backend=backend: backend)
        metrics.record_tool_call(endpoint="/rest/api/invoice#list", method="GET",
                                 outcome="success", duration_seconds=duration)
    assert await shared.wait_pending()
    result = workers[0].snapshot()["tool_call_duration_seconds"]["invoice.list|GET"]
    assert result["count"] == 2
    assert result["buckets"]["0.25"] == 1
    assert result["buckets"]["20"] == 1
    assert result["buckets"]["30"] == 2

    # Stage 385 reader scanned this exact prefix and rejected unknown families.
    old_rows = [workers[0]._redis.hgetall(key) for key in workers[0]._redis.scan_iter(
        match="vetmanager:metrics:v1:latency:*")]
    assert old_rows
    assert all(row["family"] in shared.SHARED_LATENCY_FAMILIES for row in old_rows)
    assert any(row["family"] == "tool_call_latency_seconds"
               and row["label_key"] == "/rest/api/invoice#list|GET"
               and int(row["count"]) == 2 for row in old_rows)


@pytest.mark.asyncio
async def test_overflow_keeps_histogram_distribution(monkeypatch):
    class FullCapacity:
        def acquire(self, **_kwargs):
            return False

    backend = shared.RedisMetricCounters(fakeredis.FakeRedis(decode_responses=True))
    monkeypatch.setattr(shared, "get_backend", lambda: backend)
    monkeypatch.setattr(shared, "_DELIVERY_CAPACITY", FullCapacity())
    for duration in (.2, 7., 35.):
        metrics.record_tool_call(endpoint="/rest/api/invoice#list", method="GET",
                                 outcome="success", duration_seconds=duration)
    assert await shared.wait_pending()
    histogram = backend.snapshot()["tool_call_duration_seconds"]["invoice.list|GET"]
    assert histogram["count"] == 3
    assert histogram["buckets"]["0.25"] == 1
    assert histogram["buckets"]["10"] == 2
    assert histogram["buckets"]["60"] == 3


def test_only_fixed_tool_and_status_labels_reach_storage(monkeypatch):
    monkeypatch.setattr(shared, "get_backend", lambda: None)
    metrics.reset_service_metrics()
    for endpoint, expected in (
        ("/rest/api/invoice#list", "invoice.list"),
        ("/rest/api/invoiceDocument#list", "invoiceDocument.list"),
        ("/rest/api/MedicalCards#get_by_id", "MedicalCards.get_by_id"),
        ("/rest/api/secret/12345#list", "other"),
    ):
        metrics.record_tool_call(endpoint=endpoint, method="GET", outcome="success",
                                 duration_seconds=.1)
        assert f"{expected}|GET" in metrics.snapshot_service_metrics()["tool_call_duration_seconds"]
    metrics.record_tool_call(endpoint="/rest/api/x#list", method="TRACE",
                             outcome="success", duration_seconds=.1)
    metrics.record_upstream_request(target="billing_api", status="arbitrary-from-upstream",
                                    duration_seconds=.1)
    snapshot = metrics.snapshot_service_metrics()
    assert "other|other" in snapshot["tool_call_duration_seconds"]
    assert set(snapshot["billing_api_duration_seconds"]) == {"other"}


@pytest.mark.asyncio
@respx.mock
async def test_host_resolution_counts_shared_task_not_cache_hit(monkeypatch):
    monkeypatch.setattr(shared, "get_backend", lambda: None)
    metrics.reset_service_metrics()
    domain = "stage435clinic"
    route = respx.get(f"https://billing-api.vetmanager.cloud/host/{domain}")
    route.side_effect = [httpx.ReadTimeout("slow"),
                         httpx.Response(200, json={"url": f"https://{domain}.vetmanager.cloud"})]
    try:
        first = await host_resolver.resolve_vetmanager_host(domain, max_retries=1)
        second = await host_resolver.resolve_vetmanager_host(domain, max_retries=1)
        assert first == second
        snapshot = metrics.snapshot_service_metrics()
        assert snapshot["host_resolution_duration_seconds"]["success"]["count"] == 1
        assert snapshot["billing_api_duration_seconds"]["read_timeout"]["count"] == 1
        assert snapshot["billing_api_duration_seconds"]["http_200"]["count"] == 1
    finally:
        host_resolver._resolved_host_cache.pop(domain, None)


@pytest.mark.asyncio
async def test_host_resolution_error_cancelled_and_metric_backend_failure(monkeypatch):
    metrics.reset_service_metrics()

    async def fail(*_args, **_kwargs):
        raise RuntimeError("upstream failed")

    monkeypatch.setattr(host_resolver, "_resolve_vetmanager_host_uncached_impl", fail)
    monkeypatch.setattr(shared, "get_backend", lambda: (_ for _ in ()).throw(
        RuntimeError("metrics unavailable")))
    with pytest.raises(RuntimeError, match="upstream failed"):
        await host_resolver._resolve_vetmanager_host_uncached("stage435-error", max_retries=0)
    monkeypatch.setattr(shared, "get_backend", lambda: None)
    assert metrics.snapshot_service_metrics()["host_resolution_duration_seconds"]["error"]["count"] == 1

    async def block(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(host_resolver, "_resolve_vetmanager_host_uncached_impl", block)
    task = asyncio.create_task(host_resolver._resolve_vetmanager_host_uncached(
        "stage435-cancel", max_retries=0))
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert metrics.snapshot_service_metrics()["host_resolution_duration_seconds"]["cancelled"]["count"] == 1
