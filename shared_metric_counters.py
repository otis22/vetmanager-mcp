"""Atomic Redis counters shared by MCP slots (stage 385.2c)."""

from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
import json
import hashlib
import math
import os
from threading import BoundedSemaphore, Lock


COUNTERS_KEY = "vetmanager:metrics:v1:counters"
LATENCY_KEY_PREFIX = "vetmanager:metrics:v1:latency:"
CACHE_ENTRIES_KEY_PREFIX = "vetmanager:metrics:v1:cache-entries:"
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
        digest = hashlib.sha256(f"{family}\0{label_key}".encode()).hexdigest()
        key = LATENCY_KEY_PREFIX + digest
        from redis.exceptions import WatchError

        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    current = pipe.hgetall(key)
                    count = int(current.get("count", 0)) + 1
                    total = float(current.get("sum_seconds", 0)) + duration
                    maximum = max(float(current.get("max_seconds", 0)), duration)
                    pipe.multi()
                    pipe.hset(key, mapping={
                        "family": family, "label_key": label_key, "count": count,
                        "sum_seconds": total, "max_seconds": maximum,
                    })
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Shared metric write contention")

    @staticmethod
    def _cache_slot_key(slot_identity: str) -> str:
        digest = hashlib.sha256(slot_identity.encode()).hexdigest()
        return CACHE_ENTRIES_KEY_PREFIX + digest

    def publish_cache_entries(self, slot_identity: str, count: int) -> None:
        if count < 0:
            raise ValueError("Cache entry count cannot be negative")
        self._redis.setex(self._cache_slot_key(slot_identity), 30, count)

    def clear_cache_entries(self, slot_identity: str) -> None:
        self._redis.delete(self._cache_slot_key(slot_identity))

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


def dispatch(operation) -> Future | None:
    """Keep Redis socket waits outside the async request loop with bounded work."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        operation()
        return None
    if not _DELIVERY_CAPACITY.acquire(blocking=False):
        raise SharedMetricsUnavailable("Shared metrics delivery queue is full")
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
            import redis

            _BACKEND = RedisMetricCounters(redis.Redis.from_url(
                url, decode_responses=True, socket_connect_timeout=1,
                socket_timeout=1,
            ))
            _BACKEND_URL = url
        return _BACKEND
