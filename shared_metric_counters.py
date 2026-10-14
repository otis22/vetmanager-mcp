"""Atomic Redis counters shared by MCP slots (stage 385.2c)."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import json
import hashlib
import math
import os
from threading import BoundedSemaphore, Event, Lock

import redis
from redis.exceptions import WatchError

from observability_logging import RUNTIME_LOGGER


COUNTERS_KEY = "vetmanager:metrics:v1:counters"
LATENCY_KEY_PREFIX = "vetmanager:metrics:v1:latency:"
REPORT_AI_TERMINAL_KEY_PREFIX = "vetmanager:report-ai:v1:terminal:"
CACHE_ENTRIES_KEY_PREFIX = "vetmanager:metrics:v1:cache-entries:"
CACHE_STOPPED_KEY_PREFIX = "vetmanager:metrics:v1:cache-stopped:"
SHARED_LATENCY_FAMILIES = frozenset({
    "http_request_latency_seconds", "upstream_request_latency_seconds",
    "tool_call_latency_seconds", "report_ai_job_stage_duration_seconds",
    "report_ai_job_duration_seconds", "report_ai_export_duration_seconds",
})
SHARED_COUNTER_FAMILIES = frozenset({
    "http_requests_total", "auth_failures_total", "upstream_failures_total",
    "upstream_requests_total", "tool_calls_total", "sentry_delivery_lost_total",
    "sentry_delivery_accepted_total", "known_issue_lookups_total",
    "prompt_requests_total", "token_expiry_notice_issued_total",
    "token_expiry_notice_skipped_total", "token_preset_issued_total",
    "placeholder_argument_rejections_total", "rate_limit_backend_degraded_total",
    "sanitizer_failures_total", "rest_unmapped_read_total",
    "report_export_download_total", "report_export_serve_total",
    "report_ai_long_queued_polls_total", "report_ai_stage_stall_polls_total",
    "report_ai_jobs_total", "report_ai_save_attempts_total",
    "report_ai_job_transitions_total", "report_ai_job_terminal_outcomes_total",
    "report_ai_empty_preview_guidance_issued_total",
    "report_ai_empty_preview_guidance_jobs_total",
    "report_ai_empty_preview_guidance_outcomes_total", "report_ai_exports_total",
    "report_ai_outcomes_by_code_total", "business_events_total",
    "cache_hits_total", "cache_misses_total", "cache_invalidations_total",
    "cache_evictions_total",
})
SCALAR_COUNTER_FAMILIES = frozenset({
    "sentry_delivery_accepted_total", "sanitizer_failures_total",
    "rest_unmapped_read_total", "report_ai_long_queued_polls_total",
    "report_ai_stage_stall_polls_total",
    "report_ai_empty_preview_guidance_issued_total",
    "report_ai_empty_preview_guidance_jobs_total",
    "cache_hits_total", "cache_misses_total", "cache_invalidations_total",
    "cache_evictions_total",
})


class SharedMetricsUnavailable(RuntimeError):
    """A complete shared metrics snapshot cannot be read."""


class RedisMetricCounters:
    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def ping(self) -> None:
        if not self._redis.ping():
            raise SharedMetricsUnavailable("Shared metrics Redis did not answer PING")

    def increment(self, family: str, label_key: str, count: int = 1) -> None:
        if family not in SHARED_COUNTER_FAMILIES or count <= 0:
            raise ValueError("Unsupported metric counter")
        field = json.dumps([family, label_key], separators=(",", ":"), ensure_ascii=True)
        self._redis.hincrby(COUNTERS_KEY, field, count)

    def observe(self, family: str, label_key: str, duration_seconds: float) -> None:
        """Update count, sum, and max in one optimistic Redis transaction."""
        if family not in SHARED_LATENCY_FAMILIES or not math.isfinite(duration_seconds):
            raise ValueError("Unsupported metric latency")
        duration = max(0.0, duration_seconds)
        self.observe_aggregate(family, label_key, 1, duration, duration)

    def observe_aggregate(self, family: str, label_key: str, count: int,
                          total_seconds: float, max_seconds: float) -> None:
        if family not in SHARED_LATENCY_FAMILIES or count <= 0:
            raise ValueError("Unsupported metric latency aggregate")
        digest = hashlib.sha256(f"{family}\0{label_key}".encode()).hexdigest()
        key = LATENCY_KEY_PREFIX + digest
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    current = pipe.hgetall(key)
                    merged_count = int(current.get("count", 0)) + count
                    total = float(current.get("sum_seconds", 0)) + total_seconds
                    maximum = max(float(current.get("max_seconds", 0)), max_seconds)
                    pipe.multi()
                    pipe.hset(key, mapping={
                        "family": family, "label_key": label_key, "count": merged_count,
                        "sum_seconds": total, "max_seconds": maximum,
                    })
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Shared metric write contention")

    def claim_report_ai_terminal(self, identity_digest: str, outcome: str,
                                 duration_seconds: float, ttl_seconds: int) -> bool:
        """Commit one terminal tombstone, counter and duration in one transaction."""
        if len(identity_digest) != 64 or not all(c in "0123456789abcdef" for c in identity_digest):
            raise ValueError("Invalid Report AI observation identity")
        if outcome not in {"saved", "existing_report_matched", "failed", "rejected", "abandoned_wait"}:
            raise ValueError("Invalid Report AI terminal outcome")
        if not math.isfinite(duration_seconds) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI terminal observation")
        duration = max(0.0, duration_seconds)
        tombstone = REPORT_AI_TERMINAL_KEY_PREFIX + identity_digest
        family = "report_ai_job_duration_seconds"
        latency_key = LATENCY_KEY_PREFIX + hashlib.sha256(f"{family}\0{outcome}".encode()).hexdigest()
        counter_field = json.dumps(["report_ai_job_terminal_outcomes_total", outcome],
                                   separators=(",", ":"), ensure_ascii=True)
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(tombstone, latency_key)
                    if pipe.exists(tombstone):
                        pipe.multi()
                        pipe.expire(tombstone, ttl_seconds)
                        pipe.execute()
                        return False
                    previous = pipe.hgetall(latency_key)
                    pipe.multi()
                    pipe.setex(tombstone, ttl_seconds, "1")
                    pipe.hincrby(COUNTERS_KEY, counter_field, 1)
                    pipe.hset(latency_key, mapping={
                        "family": family, "label_key": outcome,
                        "count": int(previous.get("count", 0)) + 1,
                        "sum_seconds": float(previous.get("sum_seconds", 0)) + duration,
                        "max_seconds": max(float(previous.get("max_seconds", 0)), duration),
                    })
                    pipe.execute()
                    return True
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI terminal claim contention")

    def refresh_report_ai_terminal(self, identity_digest: str, ttl_seconds: int) -> None:
        """Extend dedup while this slot still remembers a finalized job."""
        if len(identity_digest) != 64 or not all(c in "0123456789abcdef" for c in identity_digest):
            raise ValueError("Invalid Report AI observation identity")
        if ttl_seconds <= 0:
            raise ValueError("Invalid Report AI terminal TTL")
        self._redis.expire(REPORT_AI_TERMINAL_KEY_PREFIX + identity_digest, ttl_seconds)

    @staticmethod
    def _cache_slot_key(slot_identity: str) -> str:
        digest = hashlib.sha256(slot_identity.encode()).hexdigest()
        return CACHE_ENTRIES_KEY_PREFIX + digest

    def publish_cache_entries(self, slot_identity: str, count: int) -> None:
        if count < 0:
            raise ValueError("Cache entry count cannot be negative")
        gauge_key = self._cache_slot_key(slot_identity)
        stopped_key = CACHE_STOPPED_KEY_PREFIX + gauge_key.rsplit(":", 1)[1]
        for _ in range(5):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(stopped_key)
                    if pipe.exists(stopped_key):
                        return
                    pipe.multi()
                    pipe.setex(gauge_key, 30, count)
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Cache gauge write contention")

    def clear_cache_entries(self, slot_identity: str) -> None:
        gauge_key = self._cache_slot_key(slot_identity)
        stopped_key = CACHE_STOPPED_KEY_PREFIX + gauge_key.rsplit(":", 1)[1]
        with self._redis.pipeline(transaction=True) as pipe:
            pipe.setex(stopped_key, 60, "1")
            pipe.delete(gauge_key)
            pipe.execute()

    def snapshot(self) -> dict[str, dict[str, int] | int]:
        try:
            rows = self._redis.hgetall(COUNTERS_KEY)
            result: dict[str, dict[str, int] | int] = {
                family: 0 if family in SCALAR_COUNTER_FAMILIES else {}
                for family in SHARED_COUNTER_FAMILIES
            }
            for field, value in rows.items():
                family, label_key = json.loads(field)
                if family not in SHARED_COUNTER_FAMILIES:
                    raise ValueError("Unknown shared metric family")
                if family in SCALAR_COUNTER_FAMILIES:
                    if label_key:
                        raise ValueError("Scalar metric has labels")
                    result[family] = int(value)
                else:
                    result[family][label_key] = int(value)
            result.update({family: {} for family in SHARED_LATENCY_FAMILIES})
            for key in self._redis.scan_iter(match=LATENCY_KEY_PREFIX + "*"):
                row = self._redis.hgetall(key)
                family = row["family"]
                if family not in SHARED_LATENCY_FAMILIES:
                    raise ValueError("Unknown shared latency family")
                result[family][row["label_key"]] = {
                    "count": int(row["count"]),
                    "sum_seconds": float(row["sum_seconds"]),
                    "max_seconds": float(row["max_seconds"]),
                }
            result["cache_entries"] = sum(
                int(value) for key in self._redis.scan_iter(match=CACHE_ENTRIES_KEY_PREFIX + "*")
                if (value := self._redis.get(key)) is not None
            )
            return result
        except Exception as exc:
            raise SharedMetricsUnavailable("Shared metrics are unavailable") from exc


_BACKEND_LOCK = Lock()
_BACKEND_URL = ""
_BACKEND: RedisMetricCounters | None = None
_DELIVERY_POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="shared-metrics")
_DELIVERY_CAPACITY = BoundedSemaphore(4096)
_PENDING_LOCK = Lock()
_PENDING: set[Future] = set()
_OVERFLOW_LOCK = Lock()
_OVERFLOW_COUNTERS: dict[tuple, int] = {}
_OVERFLOW_LATENCIES: dict[tuple, tuple[int, float, float]] = {}
_OVERFLOW_GAUGES: dict[tuple, int] = {}
_OVERFLOW_FUTURE: Future | None = None
_OVERFLOW_STOP = Event()


def _schedule_overflow() -> Future:
    global _OVERFLOW_FUTURE
    if _OVERFLOW_FUTURE is None or _OVERFLOW_FUTURE.done():
        _OVERFLOW_FUTURE = _DELIVERY_POOL.submit(_drain_overflow)
    return _OVERFLOW_FUTURE


def coalesce_counter(backend: RedisMetricCounters, family: str,
                     label_key: str, count: int) -> Future:
    with _OVERFLOW_LOCK:
        key = (backend, family, label_key)
        _OVERFLOW_COUNTERS[key] = _OVERFLOW_COUNTERS.get(key, 0) + count
        return _schedule_overflow()


def coalesce_latency(backend: RedisMetricCounters, family: str,
                     label_key: str, duration: float) -> Future:
    with _OVERFLOW_LOCK:
        key = (backend, family, label_key)
        previous = _OVERFLOW_LATENCIES.get(key, (0, 0.0, 0.0))
        _OVERFLOW_LATENCIES[key] = (previous[0] + 1, previous[1] + duration,
                                    max(previous[2], duration))
        return _schedule_overflow()


def coalesce_cache_gauge(backend: RedisMetricCounters, slot: str,
                         count: int) -> Future:
    with _OVERFLOW_LOCK:
        _OVERFLOW_GAUGES[(backend, slot)] = count
        return _schedule_overflow()


def _drain_overflow() -> None:
    global _OVERFLOW_FUTURE
    while not _OVERFLOW_STOP.is_set():
        with _OVERFLOW_LOCK:
            if _OVERFLOW_COUNTERS:
                kind = "counter"
                key, value = _OVERFLOW_COUNTERS.popitem()
            elif _OVERFLOW_LATENCIES:
                kind = "latency"
                key, value = _OVERFLOW_LATENCIES.popitem()
            elif _OVERFLOW_GAUGES:
                kind = "gauge"
                key, value = _OVERFLOW_GAUGES.popitem()
            else:
                _OVERFLOW_FUTURE = None
                return
        backend = key[0]
        try:
            if kind == "counter":
                backend.increment(key[1], key[2], value)
            elif kind == "latency":
                backend.observe_aggregate(key[1], key[2], *value)
            else:
                backend.publish_cache_entries(key[1], value)
        except Exception as exc:
            with _OVERFLOW_LOCK:
                if kind == "counter":
                    _OVERFLOW_COUNTERS[key] = _OVERFLOW_COUNTERS.get(key, 0) + value
                elif kind == "latency":
                    current = _OVERFLOW_LATENCIES.get(key, (0, 0.0, 0.0))
                    _OVERFLOW_LATENCIES[key] = (current[0] + value[0],
                                                 current[1] + value[1],
                                                 max(current[2], value[2]))
                else:
                    _OVERFLOW_GAUGES.setdefault(key, value)
            RUNTIME_LOGGER.warning("Shared metric overflow retry", extra={
                "event_name": "shared_metric_overflow_retry",
                "error_class": type(exc).__name__,
            })
            _OVERFLOW_STOP.wait(1)


def dispatch(operation, *, on_full=None) -> Future | None:
    """Keep Redis socket waits outside the async request loop with bounded work."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        operation()
        return None
    if not _DELIVERY_CAPACITY.acquire(blocking=False):
        if on_full is None:
            raise SharedMetricsUnavailable("Shared metrics delivery queue is full")
        return on_full()
    try:
        future = _DELIVERY_POOL.submit(operation)
    except BaseException:
        _DELIVERY_CAPACITY.release()
        raise
    with _PENDING_LOCK:
        _PENDING.add(future)

    def completed(done: Future) -> None:
        with _PENDING_LOCK:
            _PENDING.discard(done)
        _DELIVERY_CAPACITY.release()

    future.add_done_callback(completed)
    return future


async def wait_pending(timeout_seconds: float = 2) -> bool:
    with _PENDING_LOCK:
        pending = tuple(_PENDING)
    with _OVERFLOW_LOCK:
        if _OVERFLOW_FUTURE is not None:
            pending += (_OVERFLOW_FUTURE,)
    if not pending:
        return True
    try:
        await asyncio.wait_for(asyncio.shield(asyncio.gather(
            *(asyncio.wrap_future(future) for future in pending),
            return_exceptions=True,
        )), timeout=timeout_seconds)
        return True
    except asyncio.TimeoutError:
        return False


def cancel_pending() -> int:
    """Discard queued outage work at shutdown after the drain deadline."""
    with _PENDING_LOCK:
        pending = tuple(_PENDING)
    with _OVERFLOW_LOCK:
        if _OVERFLOW_FUTURE is not None:
            _OVERFLOW_STOP.set()
            pending += (_OVERFLOW_FUTURE,)
    return sum(future.cancel() for future in pending)


def require_shared_metrics_config() -> None:
    if os.environ.get("MCP_WORKER_SLOTS", "1") == "3" and not os.environ.get("REDIS_URL", "").strip():
        raise ValueError("REDIS_URL is required for three MCP slots")


async def verify_shared_metrics_startup() -> None:
    require_shared_metrics_config()
    try:
        backend = get_backend()
        if backend is not None:
            await asyncio.wait_for(asyncio.to_thread(backend.ping), timeout=2)
    except Exception as exc:
        raise SharedMetricsUnavailable("Shared metrics Redis unavailable at startup") from exc


def get_backend() -> RedisMetricCounters | None:
    """Use one Redis connection pool per PID when REDIS_URL is configured."""
    global _BACKEND_URL, _BACKEND
    url = os.environ.get("REDIS_URL", "").strip()
    if not url:
        return None
    with _BACKEND_LOCK:
        if url != _BACKEND_URL or _BACKEND is None:
            _BACKEND = RedisMetricCounters(redis.Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=1,
                socket_timeout=1,
            ))
            _BACKEND_URL = url
        return _BACKEND
