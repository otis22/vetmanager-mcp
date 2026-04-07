"""Pluggable rate limit backend: in-memory or Redis-backed.

The default backend is in-memory (single-process). When REDIS_URL is set,
a Redis-backed backend is used so multiple workers share rate limit state.
"""

from __future__ import annotations

import os
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Protocol

from observability_logging import RUNTIME_LOGGER


class RateLimitBackend(Protocol):
    def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        ...

    def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        ...

    def clear(self, namespace: str, key: str) -> None:
        ...

    def reset_all(self) -> None:
        ...


class InMemoryRateLimitBackend:
    """Single-process rate limiter using deques. The default backend."""

    def __init__(self) -> None:
        self._state: dict[str, dict[str, deque[float]]] = defaultdict(lambda: defaultdict(deque))

    @staticmethod
    def _prune(entries: deque[float], *, now_ts: float, window_seconds: int) -> None:
        cutoff = now_ts - window_seconds
        while entries and entries[0] <= cutoff:
            entries.popleft()

    def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = self._state[namespace][key]
        self._prune(entries, now_ts=now_ts, window_seconds=window_seconds)
        return len(entries)

    def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = self._state[namespace][key]
        self._prune(entries, now_ts=now_ts, window_seconds=window_seconds)
        entries.append(now_ts)

    def clear(self, namespace: str, key: str) -> None:
        self._state[namespace].pop(key, None)

    def reset_all(self) -> None:
        self._state.clear()


class RedisRateLimitBackend:
    """Redis-backed rate limiter using sliding window via ZSET.

    Each (namespace, key) pair maps to a ZSET where members are unique
    timestamp+nonce strings and scores are timestamps. Window pruning happens
    on every check via ZREMRANGEBYSCORE. TTL is set to window_seconds to
    auto-expire idle keys.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    @staticmethod
    def _redis_key(namespace: str, key: str) -> str:
        return f"vmrl:{namespace}:{key}"

    def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        rkey = self._redis_key(namespace, key)
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff = now_ts - window_seconds
        self._redis.zremrangebyscore(rkey, 0, cutoff)
        return int(self._redis.zcard(rkey))

    def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        import secrets as _secrets
        rkey = self._redis_key(namespace, key)
        now_ts = datetime.now(timezone.utc).timestamp()
        member = f"{now_ts}:{_secrets.token_hex(4)}"
        pipe = self._redis.pipeline()
        pipe.zadd(rkey, {member: now_ts})
        pipe.expire(rkey, window_seconds + 1)
        pipe.execute()

    def clear(self, namespace: str, key: str) -> None:
        self._redis.delete(self._redis_key(namespace, key))

    def reset_all(self) -> None:
        # Production safety: only delete keys with our prefix
        for key in self._redis.scan_iter(match="vmrl:*"):
            self._redis.delete(key)


class _ResilientRedisBackend:
    """Wrap RedisRateLimitBackend with mid-operation fallback to in-memory.

    If a Redis operation fails (transient outage, network), we log a warning
    and degrade to a process-local InMemoryRateLimitBackend so request handling
    keeps working with weakened (per-worker) limits instead of returning 500.

    When `strict=True` (RATE_LIMIT_REQUIRE_REDIS=1), Redis errors are NOT
    swallowed: they propagate so the request fails closed and operators can
    detect the outage. This honors the operator contract that "require Redis"
    means strict enforcement, not just startup check.

    Note: clock skew between workers can distort the shared sliding window
    when running multi-worker against Redis. For current scale (single host),
    application timestamps are acceptable. Future hardening: use Redis TIME or
    a Lua script for consistent server-side timestamps.
    """

    def __init__(self, redis_backend: RedisRateLimitBackend, *, strict: bool = False) -> None:
        self._redis_backend = redis_backend
        self._fallback = InMemoryRateLimitBackend()
        self._strict = strict

    def _safe(self, op_name: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            if self._strict:
                # Strict mode: propagate the error so the request fails closed.
                RUNTIME_LOGGER.error(
                    "Redis rate limit operation failed in strict mode.",
                    extra={
                        "event_name": "rate_limit_backend_strict_failure",
                        "operation": op_name,
                        "error": str(exc),
                    },
                )
                raise
            RUNTIME_LOGGER.warning(
                "Redis rate limit operation failed, degrading to in-memory.",
                extra={
                    "event_name": "rate_limit_backend_runtime_fallback",
                    "operation": op_name,
                    "error": str(exc),
                },
            )
            return None

    def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        result = self._safe(
            "count_in_window",
            self._redis_backend.count_in_window,
            namespace, key, window_seconds=window_seconds,
        )
        if result is None:
            return self._fallback.count_in_window(namespace, key, window_seconds=window_seconds)
        return result

    def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        if self._safe(
            "record_hit",
            self._redis_backend.record_hit,
            namespace, key, window_seconds=window_seconds,
        ) is None:
            self._fallback.record_hit(namespace, key, window_seconds=window_seconds)

    def clear(self, namespace: str, key: str) -> None:
        self._safe("clear", self._redis_backend.clear, namespace, key)
        self._fallback.clear(namespace, key)

    def reset_all(self) -> None:
        self._safe("reset_all", self._redis_backend.reset_all)
        self._fallback.reset_all()


_BACKEND: RateLimitBackend | None = None


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def get_rate_limit_backend() -> RateLimitBackend:
    """Return the active rate limit backend, initializing on first call."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    redis_url = os.environ.get("REDIS_URL", "").strip()
    require_redis = _is_truthy_env("RATE_LIMIT_REQUIRE_REDIS")
    if redis_url:
        try:
            import redis as _redis_lib
            client = _redis_lib.Redis.from_url(redis_url, decode_responses=True)
            client.ping()
            redis_backend = RedisRateLimitBackend(client)
            _BACKEND = _ResilientRedisBackend(redis_backend, strict=require_redis)
            RUNTIME_LOGGER.info(
                "Rate limit backend initialized: redis",
                extra={"event_name": "rate_limit_backend_init", "backend": "redis"},
            )
            return _BACKEND
        except Exception as exc:
            if require_redis:
                # Production fail-fast: do not silently degrade.
                raise RuntimeError(
                    f"RATE_LIMIT_REQUIRE_REDIS=1 but Redis is unavailable: {exc}"
                ) from exc
            RUNTIME_LOGGER.warning(
                "Redis rate limit backend unavailable, falling back to in-memory.",
                extra={
                    "event_name": "rate_limit_backend_fallback",
                    "error": str(exc),
                },
            )

    _BACKEND = InMemoryRateLimitBackend()
    RUNTIME_LOGGER.info(
        "Rate limit backend initialized: in_memory",
        extra={"event_name": "rate_limit_backend_init", "backend": "in_memory"},
    )
    return _BACKEND


def reset_rate_limit_backend() -> None:
    """Force re-initialization on next get_rate_limit_backend() call (test only)."""
    global _BACKEND
    _BACKEND = None
