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
REPORT_AI_LIFECYCLE_KEY_PREFIX = "vetmanager:report-ai:v1:lifecycle:"
REPORT_AI_EXPIRY_INDEX = "vetmanager:report-ai:v1:expiry"
REPORT_AI_GUIDANCE_KEY_PREFIX = "vetmanager:report-ai:v1:guidance:"
REPORT_AI_GUIDANCE_EXPIRY_INDEX = "vetmanager:report-ai:v1:guidance-expiry"
REPORT_AI_GUIDANCE_ACCOUNT_PREFIX = "vetmanager:report-ai:v1:guidance-account:"
REPORT_AI_EXPORT_KEY_PREFIX = "vetmanager:report-ai:v1:export:"
REPORT_AI_EXPORT_DONE_PREFIX = "vetmanager:report-ai:v1:export-done:"
REPORT_AI_EXPORT_EXPIRY_INDEX = "vetmanager:report-ai:v1:export-expiry"
REPORT_AI_QUEUE_KEY_PREFIX = "vetmanager:report-ai:v1:queue:"
REPORT_AI_REJECT_PENDING_PREFIX = "vetmanager:report-ai:v1:reject-pending:"
ACTIVATION_SCAN_LEASE_KEY = "vetmanager:activation:v1:scan-lease"
ACTIVATION_SNAPSHOT_KEY = "vetmanager:activation:v1:snapshot"
ACTIVATION_ALERTS_KEY = "vetmanager:activation:v1:alerts"
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

    def claim_activation_scan(self, owner: str) -> bool:
        return bool(self._redis.set(ACTIVATION_SCAN_LEASE_KEY, owner, nx=True, ex=60))

    def release_activation_scan(self, owner: str) -> bool:
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(ACTIVATION_SCAN_LEASE_KEY)
                    if pipe.get(ACTIVATION_SCAN_LEASE_KEY) != owner:
                        return False
                    pipe.multi()
                    pipe.delete(ACTIVATION_SCAN_LEASE_KEY)
                    pipe.execute()
                    return True
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Activation scan lease contention")

    def publish_activation_snapshot(self, values: dict) -> None:
        self._redis.set(ACTIVATION_SNAPSHOT_KEY,
                        json.dumps(values, separators=(",", ":")), ex=180)

    def activation_snapshot(self) -> dict:
        raw = self._redis.get(ACTIVATION_SNAPSHOT_KEY)
        return json.loads(raw) if raw else {}

    def claim_activation_alert(self, identity_digest: str, threshold: int) -> bool:
        if len(identity_digest) != 64 or threshold not in (24, 72):
            raise ValueError("Invalid activation alert identity")
        return bool(self._redis.hsetnx(ACTIVATION_ALERTS_KEY,
                                        f"{identity_digest}:{threshold}", "1"))

    def clear_activation_alerts(self, identity_digest: str) -> None:
        if len(identity_digest) != 64:
            raise ValueError("Invalid activation alert identity")
        self._redis.hdel(ACTIVATION_ALERTS_KEY,
                         f"{identity_digest}:24", f"{identity_digest}:72")

    def reconcile_activation_alerts(self, live_digests: set[str]) -> None:
        stale = [field for field in self._redis.hscan_iter(ACTIVATION_ALERTS_KEY)
                 if field[0].split(":", 1)[0] not in live_digests]
        if stale:
            self._redis.hdel(ACTIVATION_ALERTS_KEY, *(field for field, _ in stale))

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

    def observe_report_ai_queue(self, identity_digest: str, queued: bool,
                                now: float, ttl_seconds: int) -> int | None:
        if len(identity_digest) != 64 or not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI queue observation")
        key = REPORT_AI_QUEUE_KEY_PREFIX + identity_digest
        if not queued:
            self._redis.delete(key)
            return None
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    first = pipe.hget(key, "first_seen")
                    first_seen = float(first) if first is not None else now
                    pipe.multi()
                    pipe.hset(key, mapping={"first_seen": first_seen, "last_seen": now})
                    pipe.expire(key, ttl_seconds)
                    pipe.execute()
                    return max(0, int(now - first_seen))
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI queue observation contention")

    def mark_report_ai_reject_pending(self, identity_digest: str, ttl_seconds: int) -> None:
        if len(identity_digest) != 64 or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI reject observation")
        self._redis.setex(REPORT_AI_REJECT_PENDING_PREFIX + identity_digest, ttl_seconds, "1")

    def report_ai_reject_pending(self, identity_digest: str, *, terminal: bool = False) -> bool:
        if len(identity_digest) != 64:
            raise ValueError("Invalid Report AI reject observation")
        key = REPORT_AI_REJECT_PENDING_PREFIX + identity_digest
        if terminal:
            self._redis.delete(key)
            return False
        return bool(self._redis.exists(key))

    def report_ai_export_wait_age(self, identity_digest: str, now: float) -> int | None:
        if len(identity_digest) != 64 or not math.isfinite(now):
            raise ValueError("Invalid Report AI export observation")
        started = self._redis.hget(REPORT_AI_EXPORT_KEY_PREFIX + identity_digest, "started_at")
        return max(0, int(now - float(started))) if started is not None else None

    def report_ai_stage_age(self, identity_digest: str, stage: str,
                            now: float) -> int | None:
        state = self._redis.hgetall(REPORT_AI_LIFECYCLE_KEY_PREFIX + identity_digest)
        if not state or state.get("stage") != stage:
            return None
        return max(0, int(now - float(state["stage_started"])))

    def observe_report_ai_lifecycle(self, identity_digest: str, stage: str,
                                    now: float, ttl_seconds: int,
                                    *, expiry_only: bool = False,
                                    force: bool = False,
                                    expected_expiry_at: float | None = None) -> bool:
        """Move one job stage and its metric deltas in a Redis transaction."""
        if len(identity_digest) != 64 or not all(c in "0123456789abcdef" for c in identity_digest):
            raise ValueError("Invalid Report AI observation identity")
        if stage not in {"queued", "recognized", "preview", "ready_to_save",
                         "needs_confirmation", "saved", "existing_report_matched",
                         "failed", "rejected", "unknown", "abandoned_wait"}:
            raise ValueError("Invalid Report AI stage")
        if not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI observation time")
        state_key = REPORT_AI_LIFECYCLE_KEY_PREFIX + identity_digest
        tombstone = REPORT_AI_TERMINAL_KEY_PREFIX + identity_digest
        terminal = stage in {"saved", "existing_report_matched", "failed", "rejected", "abandoned_wait"}
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(state_key, tombstone)
                    state = pipe.hgetall(state_key)
                    if pipe.exists(tombstone):
                        pipe.multi()
                        pipe.expire(tombstone, ttl_seconds)
                        pipe.delete(state_key)
                        pipe.zrem(REPORT_AI_EXPIRY_INDEX, identity_digest)
                        pipe.execute()
                        return False
                    if (force and state and expected_expiry_at is not None
                            and abs(float(state["last_seen"]) + ttl_seconds
                                    - expected_expiry_at) > 1e-6):
                        return False
                    if (expiry_only and not force and state
                            and now - float(state["last_seen"]) < ttl_seconds):
                        return False
                    if state and not expiry_only and now < float(state["last_seen"]):
                        return False
                    if not state and expiry_only:
                        pipe.multi()
                        pipe.zrem(REPORT_AI_EXPIRY_INDEX, identity_digest)
                        pipe.execute()
                        return False
                    if not state and not terminal:
                        pipe.multi()
                        pipe.hset(state_key, mapping={
                            "first_seen": now, "last_seen": now,
                            "stage": stage, "stage_started": now,
                        })
                        pipe.zadd(REPORT_AI_EXPIRY_INDEX, {identity_digest: now + ttl_seconds})
                        pipe.execute()
                        return False
                    previous = state.get("stage")
                    if previous == stage and not expiry_only:
                        pipe.multi()
                        pipe.hset(state_key, "last_seen", now)
                        pipe.zadd(REPORT_AI_EXPIRY_INDEX, {identity_digest: now + ttl_seconds})
                        pipe.execute()
                        return False
                    durations = []
                    if state:
                        durations.append(("report_ai_job_stage_duration_seconds", previous,
                                          max(0.0, now - float(state["stage_started"]))))
                    if terminal:
                        if stage != "abandoned_wait":
                            durations.append(("report_ai_job_stage_duration_seconds", stage, 0.0))
                        durations.append((
                            "report_ai_job_duration_seconds", stage,
                            max(0.0, now - float(state["first_seen"])) if state else 0.0,
                        ))
                    latency_values = []
                    for family, label, duration in durations:
                        key = LATENCY_KEY_PREFIX + hashlib.sha256(f"{family}\0{label}".encode()).hexdigest()
                        pipe.watch(key)
                        latency_values.append((key, family, label, duration, pipe.hgetall(key)))
                    pipe.multi()
                    if previous:
                        field = json.dumps(["report_ai_job_transitions_total", f"{previous}|{stage}"],
                                           separators=(",", ":"), ensure_ascii=True)
                        pipe.hincrby(COUNTERS_KEY, field, 1)
                    if terminal:
                        field = json.dumps(["report_ai_job_terminal_outcomes_total", stage],
                                           separators=(",", ":"), ensure_ascii=True)
                        pipe.setex(tombstone, ttl_seconds, "1")
                        pipe.hincrby(COUNTERS_KEY, field, 1)
                        pipe.delete(state_key)
                        pipe.zrem(REPORT_AI_EXPIRY_INDEX, identity_digest)
                    else:
                        pipe.hset(state_key, mapping={"stage": stage, "stage_started": now,
                                                      "last_seen": now})
                        pipe.zadd(REPORT_AI_EXPIRY_INDEX, {identity_digest: now + ttl_seconds})
                    for key, family, label, duration, previous_latency in latency_values:
                        pipe.hset(key, mapping={
                            "family": family, "label_key": label,
                            "count": int(previous_latency.get("count", 0)) + 1,
                            "sum_seconds": float(previous_latency.get("sum_seconds", 0)) + duration,
                            "max_seconds": max(float(previous_latency.get("max_seconds", 0)), duration),
                        })
                    pipe.execute()
                    return terminal
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI lifecycle contention")

    def cleanup_report_ai_lifecycle(self, now: float, ttl_seconds: int,
                                    limit: int = 100,
                                    max_entries: int = 4096) -> int:
        """Finalize a bounded set of expired observations, including idle jobs."""
        digests = self._redis.zrangebyscore(REPORT_AI_EXPIRY_INDEX, "-inf", now,
                                             start=0, num=limit)
        for digest in digests:
            self.observe_report_ai_lifecycle(digest, "abandoned_wait", now, ttl_seconds,
                                             expiry_only=True)
        overflow = max(0, self._redis.zcard(REPORT_AI_EXPIRY_INDEX) - max_entries)
        for digest, score in self._redis.zrange(
                REPORT_AI_EXPIRY_INDEX, 0, min(overflow, limit) - 1,
                withscores=True) if overflow else ():
            self.observe_report_ai_lifecycle(digest, "abandoned_wait", now, ttl_seconds,
                                             expiry_only=True, force=True,
                                             expected_expiry_at=score)
        return len(digests) + min(overflow, limit)

    def refresh_report_ai_terminal(self, identity_digest: str, ttl_seconds: int) -> None:
        """Extend dedup while this slot still remembers a finalized job."""
        if len(identity_digest) != 64 or not all(c in "0123456789abcdef" for c in identity_digest):
            raise ValueError("Invalid Report AI observation identity")
        if ttl_seconds <= 0:
            raise ValueError("Invalid Report AI terminal TTL")
        self._redis.expire(REPORT_AI_TERMINAL_KEY_PREFIX + identity_digest, ttl_seconds)

    def issue_report_ai_guidance(self, identity_digest: str, now: float,
                                 ttl_seconds: int, *, account_digest: str | None = None,
                                 max_account_entries: int = 4096) -> bool:
        """Count every issued response, but one first issue per logical job."""
        if len(identity_digest) != 64 or not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI guidance observation")
        if ((account_digest is not None and len(account_digest) != 64)
                or max_account_entries <= 0):
            raise ValueError("Invalid Report AI guidance account")
        key = REPORT_AI_GUIDANCE_KEY_PREFIX + identity_digest
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    state = pipe.hgetall(key)
                    first = "issued_at" not in state
                    pending_outcome = (state.get("pending_outcome") if first
                                       and float(state.get("pending_at", "-inf")) >= now
                                       else None)
                    latest_seen = max(float(state.get("last_seen", now)), now)
                    pipe.multi()
                    pipe.hincrby(COUNTERS_KEY, json.dumps([
                        "report_ai_empty_preview_guidance_issued_total", ""],
                        separators=(",", ":")), 1)
                    if first:
                        pipe.hincrby(COUNTERS_KEY, json.dumps([
                            "report_ai_empty_preview_guidance_jobs_total", ""],
                            separators=(",", ":")), 1)
                        pipe.hset(key, mapping={"issued_at": now, "last_seen": latest_seen,
                                                "outcome": pending_outcome or "",
                                                "account_digest": account_digest or ""})
                        if state.get("pending_outcome"):
                            pipe.hdel(key, "pending_outcome", "pending_at")
                        if pending_outcome:
                            pipe.hincrby(COUNTERS_KEY, json.dumps([
                                "report_ai_empty_preview_guidance_outcomes_total",
                                pending_outcome], separators=(",", ":")), 1)
                    else:
                        pipe.hset(key, "last_seen", latest_seen)
                    if state.get("outcome") or pending_outcome:
                        pipe.expire(key, ttl_seconds)
                    else:
                        pipe.zadd(REPORT_AI_GUIDANCE_EXPIRY_INDEX,
                                  {identity_digest: latest_seen + ttl_seconds})
                    if account_digest is not None and not (state.get("outcome") or pending_outcome):
                        account_key = REPORT_AI_GUIDANCE_ACCOUNT_PREFIX + account_digest
                        pipe.zadd(account_key, {identity_digest: latest_seen})
                        pipe.zremrangebyscore(account_key, "-inf", now - ttl_seconds)
                        pipe.zremrangebyrank(account_key, 0, -max_account_entries - 1)
                        pipe.expire(account_key, ttl_seconds)
                    pipe.execute()
                    return first
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI guidance issue contention")

    def resolve_recreated_report_ai_guidance(self, account_digest: str,
                                             new_job_digest: str, now: float,
                                             ttl_seconds: int) -> int:
        if len(account_digest) != 64 or len(new_job_digest) != 64:
            raise ValueError("Invalid Report AI recreated observation")
        account_key = REPORT_AI_GUIDANCE_ACCOUNT_PREFIX + account_digest
        digests = self._redis.zrangebyscore(account_key, now - ttl_seconds, now)
        resolved = sum(bool(self.resolve_report_ai_guidance(
            digest, "recreated", now, ttl_seconds))
            for digest in digests if digest != new_job_digest)
        self._redis.zremrangebyscore(account_key, "-inf", now - ttl_seconds)
        return resolved

    def resolve_report_ai_guidance(self, identity_digest: str, outcome: str,
                                   now: float, ttl_seconds: int,
                                   *, expiry_only: bool = False,
                                   force: bool = False,
                                   expected_expiry_at: float | None = None) -> bool:
        if len(identity_digest) != 64 or outcome not in {
            "recreated", "saved_empty", "abandoned_wait", "preview_changed",
        } or not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI guidance outcome")
        key = REPORT_AI_GUIDANCE_KEY_PREFIX + identity_digest
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key)
                    state = pipe.hgetall(key)
                    if not state and not expiry_only and outcome != "abandoned_wait":
                        pipe.multi()
                        pipe.hset(key, mapping={"pending_outcome": outcome,
                                                "pending_at": now,
                                                "last_seen": now})
                        pipe.expire(key, ttl_seconds)
                        pipe.execute()
                        return False
                    if not state or state.get("outcome") or state.get("pending_outcome"):
                        return False
                    if (force and expected_expiry_at is not None
                            and abs(float(state["last_seen"]) + ttl_seconds
                                    - expected_expiry_at) > 1e-6):
                        return False
                    if (expiry_only and not force
                            and now - float(state["last_seen"]) < ttl_seconds):
                        return False
                    field = json.dumps(["report_ai_empty_preview_guidance_outcomes_total",
                                        outcome], separators=(",", ":"))
                    pipe.multi()
                    pipe.hset(key, "outcome", outcome)
                    pipe.expire(key, ttl_seconds)
                    pipe.zrem(REPORT_AI_GUIDANCE_EXPIRY_INDEX, identity_digest)
                    if state.get("account_digest"):
                        pipe.zrem(REPORT_AI_GUIDANCE_ACCOUNT_PREFIX + state["account_digest"],
                                  identity_digest)
                    pipe.hincrby(COUNTERS_KEY, field, 1)
                    pipe.execute()
                    return True
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI guidance outcome contention")

    def cleanup_report_ai_guidance(self, now: float, ttl_seconds: int,
                                   limit: int = 100,
                                   max_entries: int = 4096) -> int:
        digests = self._redis.zrangebyscore(REPORT_AI_GUIDANCE_EXPIRY_INDEX,
                                            "-inf", now, start=0, num=limit)
        for digest in digests:
            if not self.resolve_report_ai_guidance(digest, "abandoned_wait", now,
                                                   ttl_seconds, expiry_only=True):
                # A resolved or missing record must leave the index too.
                key = REPORT_AI_GUIDANCE_KEY_PREFIX + digest
                if not self._redis.exists(key) or self._redis.hget(key, "outcome"):
                    self._redis.zrem(REPORT_AI_GUIDANCE_EXPIRY_INDEX, digest)
        overflow = max(0, self._redis.zcard(REPORT_AI_GUIDANCE_EXPIRY_INDEX) - max_entries)
        for digest, score in self._redis.zrange(
                REPORT_AI_GUIDANCE_EXPIRY_INDEX, 0, min(overflow, limit) - 1,
                withscores=True) if overflow else ():
            self.resolve_report_ai_guidance(
                digest, "abandoned_wait", now, ttl_seconds,
                expiry_only=True, force=True, expected_expiry_at=score)
        return len(digests) + min(overflow, limit)

    def remember_report_ai_export(self, identity_digest: str, now: float,
                                  ttl_seconds: int) -> None:
        if len(identity_digest) != 64 or not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI export observation")
        key = REPORT_AI_EXPORT_KEY_PREFIX + identity_digest
        done = REPORT_AI_EXPORT_DONE_PREFIX + identity_digest
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key, done)
                    if pipe.exists(done):
                        return
                    state = pipe.hgetall(key)
                    pipe.multi()
                    if not state:
                        pipe.hset(key, mapping={"started_at": now, "last_seen": now,
                                                "has_polled": 0})
                    else:
                        pipe.hset(key, mapping={
                            "started_at": min(float(state["started_at"]), now),
                            "last_seen": max(float(state["last_seen"]), now),
                        })
                    pipe.zadd(REPORT_AI_EXPORT_EXPIRY_INDEX,
                              {identity_digest: max(float(state.get("last_seen", now)), now)
                               + ttl_seconds})
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI export start contention")

    def mark_report_ai_export_poll(self, identity_digest: str, now: float,
                                   ttl_seconds: int) -> None:
        key = REPORT_AI_EXPORT_KEY_PREFIX + identity_digest
        done = REPORT_AI_EXPORT_DONE_PREFIX + identity_digest
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key, done)
                    if pipe.exists(done):
                        return
                    state = pipe.hgetall(key)
                    latest_seen = max(float(state.get("last_seen", now)), now)
                    pipe.multi()
                    values = {"last_seen": latest_seen, "has_polled": 1}
                    if not state:
                        values["started_at"] = now
                    pipe.hset(key, mapping=values)
                    pipe.zadd(REPORT_AI_EXPORT_EXPIRY_INDEX,
                              {identity_digest: latest_seen + ttl_seconds})
                    pipe.execute()
                    return
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI export poll contention")

    def complete_report_ai_export(self, identity_digest: str, outcome: str,
                                  now: float, ttl_seconds: int,
                                  *, expiry_only: bool = False,
                                  force: bool = False,
                                  expected_expiry_at: float | None = None) -> bool:
        if len(identity_digest) != 64 or outcome not in {
            "success", "error", "abandoned_wait",
        } or not math.isfinite(now) or ttl_seconds <= 0:
            raise ValueError("Invalid Report AI export outcome")
        key = REPORT_AI_EXPORT_KEY_PREFIX + identity_digest
        done = REPORT_AI_EXPORT_DONE_PREFIX + identity_digest
        latency_key = LATENCY_KEY_PREFIX + hashlib.sha256(
            f"report_ai_export_duration_seconds\0{outcome}".encode()).hexdigest()
        for _ in range(20):
            try:
                with self._redis.pipeline() as pipe:
                    pipe.watch(key, done, latency_key)
                    if pipe.exists(done):
                        pipe.multi()
                        pipe.zrem(REPORT_AI_EXPORT_EXPIRY_INDEX, identity_digest)
                        pipe.execute()
                        return False
                    state = pipe.hgetall(key)
                    if (force and state and expected_expiry_at is not None
                            and abs(float(state["last_seen"]) + ttl_seconds
                                    - expected_expiry_at) > 1e-6):
                        return False
                    if expiry_only and (not state or
                            not force and now - float(state["last_seen"]) < ttl_seconds):
                        if not state:
                            pipe.multi()
                            pipe.zrem(REPORT_AI_EXPORT_EXPIRY_INDEX, identity_digest)
                            pipe.execute()
                        return False
                    operation = ("poll" if state.get("has_polled") == "1" else "start")
                    if outcome != "abandoned_wait":
                        operation = "poll"
                    previous_latency = pipe.hgetall(latency_key) if state else {}
                    field = json.dumps(["report_ai_exports_total", f"{operation}|{outcome}"],
                                       separators=(",", ":"))
                    pipe.multi()
                    pipe.setex(done, ttl_seconds, "1")
                    pipe.hincrby(COUNTERS_KEY, field, 1)
                    if state:
                        duration = max(0.0, now - float(state["started_at"]))
                        pipe.hset(latency_key, mapping={
                            "family": "report_ai_export_duration_seconds",
                            "label_key": outcome,
                            "count": int(previous_latency.get("count", 0)) + 1,
                            "sum_seconds": float(previous_latency.get("sum_seconds", 0)) + duration,
                            "max_seconds": max(float(previous_latency.get("max_seconds", 0)), duration),
                        })
                    pipe.delete(key)
                    pipe.zrem(REPORT_AI_EXPORT_EXPIRY_INDEX, identity_digest)
                    pipe.execute()
                    return True
            except WatchError:
                continue
        raise SharedMetricsUnavailable("Report AI export outcome contention")

    def cleanup_report_ai_exports(self, now: float, ttl_seconds: int,
                                  limit: int = 100,
                                  max_entries: int = 4096) -> int:
        digests = self._redis.zrangebyscore(REPORT_AI_EXPORT_EXPIRY_INDEX,
                                            "-inf", now, start=0, num=limit)
        for digest in digests:
            self.complete_report_ai_export(digest, "abandoned_wait", now,
                                           ttl_seconds, expiry_only=True)
        overflow = max(0, self._redis.zcard(REPORT_AI_EXPORT_EXPIRY_INDEX) - max_entries)
        for digest, score in self._redis.zrange(
                REPORT_AI_EXPORT_EXPIRY_INDEX, 0, min(overflow, limit) - 1,
                withscores=True) if overflow else ():
            self.complete_report_ai_export(
                digest, "abandoned_wait", now, ttl_seconds,
                expiry_only=True, force=True, expected_expiry_at=score)
        return len(digests) + min(overflow, limit)

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
