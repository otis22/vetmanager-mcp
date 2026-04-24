"""Pluggable rate limit backend: in-memory or Redis-backed.

The default backend is in-memory (single-process). When REDIS_URL is set,
a Redis-backed backend is used so multiple workers share rate limit state.
"""

from __future__ import annotations

import asyncio
import importlib
import inspect
import os
import secrets
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Protocol

from env_utils import env_float, env_int
from observability_logging import RUNTIME_LOGGER
from service_metrics import record_rate_limit_backend_degraded


DEFAULT_REDIS_SOCKET_TIMEOUT_SECONDS = 1.0
DEFAULT_REDIS_OPERATION_TIMEOUT_SECONDS = 1.0
DEFAULT_REDIS_HEALTH_CHECK_INTERVAL_SECONDS = 30


class RateLimitBackend(Protocol):
    async def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        ...

    async def consume_hit(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, bool]:
        ...

    async def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        ...

    async def clear(self, namespace: str, key: str) -> None:
        ...

    async def reset_all(self) -> None:
        ...

    async def close(self) -> None:
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

    async def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = self._state[namespace][key]
        self._prune(entries, now_ts=now_ts, window_seconds=window_seconds)
        return len(entries)

    async def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = self._state[namespace][key]
        self._prune(entries, now_ts=now_ts, window_seconds=window_seconds)
        entries.append(now_ts)

    async def consume_hit(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, bool]:
        now_ts = datetime.now(timezone.utc).timestamp()
        entries = self._state[namespace][key]
        self._prune(entries, now_ts=now_ts, window_seconds=window_seconds)
        if len(entries) >= limit:
            return len(entries), False
        entries.append(now_ts)
        return len(entries), True

    async def clear(self, namespace: str, key: str) -> None:
        self._state[namespace].pop(key, None)

    async def reset_all(self) -> None:
        self._state.clear()

    async def close(self) -> None:
        return None


class RedisRateLimitBackend:
    """Redis-backed rate limiter using sliding window via ZSET.

    Each (namespace, key) pair maps to a ZSET where members are unique
    timestamp+nonce strings and scores are timestamps. Window pruning happens
    on every check via ZREMRANGEBYSCORE. TTL is set to window_seconds to
    auto-expire idle keys.
    """

    def __init__(self, redis_client) -> None:
        self._redis = redis_client
        try:
            self._watch_error = importlib.import_module("redis.exceptions").WatchError
        except Exception:  # pragma: no cover
            self._watch_error = RuntimeError

    @staticmethod
    def _redis_key(namespace: str, key: str) -> str:
        return f"vmrl:{namespace}:{key}"

    @staticmethod
    def _ttl_seconds(window_seconds: int) -> int:
        return window_seconds + 1

    async def _append_hit_transaction(
        self,
        pipe,
        *,
        rkey: str,
        member: str,
        now_ts: float,
        window_seconds: int,
    ) -> None:
        zadd_result = pipe.zadd(rkey, {member: now_ts})
        if inspect.isawaitable(zadd_result):
            await zadd_result
        expire_result = pipe.expire(rkey, self._ttl_seconds(window_seconds))
        if inspect.isawaitable(expire_result):
            await expire_result

    async def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        rkey = self._redis_key(namespace, key)
        now_ts = datetime.now(timezone.utc).timestamp()
        cutoff = now_ts - window_seconds
        await self._redis.zremrangebyscore(rkey, 0, cutoff)
        return int(await self._redis.zcard(rkey))

    async def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        rkey = self._redis_key(namespace, key)
        now_ts = datetime.now(timezone.utc).timestamp()
        member = f"{now_ts}:{secrets.token_hex(4)}"
        pipe = self._redis.pipeline()
        try:
            multi = getattr(pipe, "multi", None)
            if callable(multi):
                multi()
            await self._append_hit_transaction(
                pipe,
                rkey=rkey,
                member=member,
                now_ts=now_ts,
                window_seconds=window_seconds,
            )
            await pipe.execute()
        finally:
            reset = getattr(pipe, "reset", None)
            if callable(reset):
                reset_result = reset()
                if inspect.isawaitable(reset_result):
                    await reset_result

    async def consume_hit(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, bool]:
        rkey = self._redis_key(namespace, key)
        for _ in range(8):
            now_ts = datetime.now(timezone.utc).timestamp()
            cutoff = now_ts - window_seconds
            member = f"{now_ts}:{secrets.token_hex(4)}"
            pipe = self._redis.pipeline()
            try:
                await pipe.watch(rkey)
                await pipe.zremrangebyscore(rkey, 0, cutoff)
                current = int(await pipe.zcard(rkey))
                if current >= limit:
                    return current, False
                multi = getattr(pipe, "multi", None)
                if callable(multi):
                    multi()
                await self._append_hit_transaction(
                    pipe,
                    rkey=rkey,
                    member=member,
                    now_ts=now_ts,
                    window_seconds=window_seconds,
                )
                await pipe.execute()
                return current + 1, True
            except self._watch_error:
                continue
            finally:
                reset = getattr(pipe, "reset", None)
                if callable(reset):
                    reset_result = reset()
                    if inspect.isawaitable(reset_result):
                        await reset_result
        raise RuntimeError("rate limit consume conflict after retries")

    async def clear(self, namespace: str, key: str) -> None:
        await self._redis.delete(self._redis_key(namespace, key))

    async def reset_all(self) -> None:
        # Production safety: only delete keys with our prefix
        async for key in self._redis.scan_iter(match="vmrl:*"):
            await self._redis.delete(key)

    async def close(self) -> None:
        aclose = getattr(self._redis, "aclose", None)
        if callable(aclose):
            await aclose()


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

    def __init__(
        self,
        redis_backend: RedisRateLimitBackend,
        *,
        strict: bool = False,
        operation_timeout_seconds: float | None = None,
    ) -> None:
        self._redis_backend = redis_backend
        self._fallback = InMemoryRateLimitBackend()
        self._strict = strict
        self._operation_timeout_seconds = (
            operation_timeout_seconds
            if operation_timeout_seconds is not None
            else _get_redis_operation_timeout_seconds()
        )

    async def _safe(self, op_name: str, fn, *args, **kwargs):
        try:
            return await asyncio.wait_for(
                fn(*args, **kwargs),
                timeout=self._operation_timeout_seconds,
            )
        except (asyncio.TimeoutError, TimeoutError) as exc:
            reason = "strict_failure" if self._strict else "timeout"
            record_rate_limit_backend_degraded(reason)
            if self._strict:
                RUNTIME_LOGGER.error(
                    "Redis rate limit operation timed out in strict mode.",
                    extra={
                        "event_name": "rate_limit_backend_strict_failure",
                        "operation": op_name,
                        "error": str(exc),
                    },
                )
                raise
            RUNTIME_LOGGER.warning(
                "Redis rate limit operation timed out, degrading to in-memory.",
                extra={
                    "event_name": "rate_limit_backend_runtime_fallback",
                    "operation": op_name,
                    "error": str(exc),
                },
            )
            return None
        except Exception as exc:
            if self._strict:
                # Strict mode: propagate the error so the request fails closed.
                record_rate_limit_backend_degraded("strict_failure")
                RUNTIME_LOGGER.error(
                    "Redis rate limit operation failed in strict mode.",
                    extra={
                        "event_name": "rate_limit_backend_strict_failure",
                        "operation": op_name,
                        "error": str(exc),
                    },
                )
                raise
            record_rate_limit_backend_degraded("error")
            RUNTIME_LOGGER.warning(
                "Redis rate limit operation failed, degrading to in-memory.",
                extra={
                    "event_name": "rate_limit_backend_runtime_fallback",
                    "operation": op_name,
                    "error": str(exc),
                },
            )
            return None

    async def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
        result = await self._safe(
            "count_in_window",
            self._redis_backend.count_in_window,
            namespace, key, window_seconds=window_seconds,
        )
        if result is None:
            return await self._fallback.count_in_window(namespace, key, window_seconds=window_seconds)
        return result

    async def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
        if await self._safe(
            "record_hit",
            self._redis_backend.record_hit,
            namespace, key, window_seconds=window_seconds,
        ) is None:
            await self._fallback.record_hit(namespace, key, window_seconds=window_seconds)

    async def consume_hit(
        self,
        namespace: str,
        key: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> tuple[int, bool]:
        result = await self._safe(
            "consume_hit",
            self._redis_backend.consume_hit,
            namespace,
            key,
            limit=limit,
            window_seconds=window_seconds,
        )
        if result is None:
            return await self._fallback.consume_hit(
                namespace,
                key,
                limit=limit,
                window_seconds=window_seconds,
            )
        return result

    async def clear(self, namespace: str, key: str) -> None:
        await self._safe("clear", self._redis_backend.clear, namespace, key)
        await self._fallback.clear(namespace, key)

    async def reset_all(self) -> None:
        await self._safe("reset_all", self._redis_backend.reset_all)
        await self._fallback.reset_all()

    async def close(self) -> None:
        await self._redis_backend.close()
        await self._fallback.close()


_BACKEND: RateLimitBackend | None = None
_BACKEND_INIT_LOCK: asyncio.Lock | None = None


def _is_truthy_env(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _get_redis_socket_timeout_seconds() -> float:
    return env_float(
        "RATE_LIMIT_REDIS_SOCKET_TIMEOUT_SECONDS",
        DEFAULT_REDIS_SOCKET_TIMEOUT_SECONDS,
    )


def _get_redis_operation_timeout_seconds() -> float:
    return env_float(
        "RATE_LIMIT_REDIS_OPERATION_TIMEOUT_SECONDS",
        DEFAULT_REDIS_OPERATION_TIMEOUT_SECONDS,
    )


def _get_redis_health_check_interval_seconds() -> int:
    return env_int(
        "RATE_LIMIT_REDIS_HEALTH_CHECK_INTERVAL_SECONDS",
        DEFAULT_REDIS_HEALTH_CHECK_INTERVAL_SECONDS,
    )


def _get_backend_init_lock() -> asyncio.Lock:
    global _BACKEND_INIT_LOCK
    if _BACKEND_INIT_LOCK is None:
        _BACKEND_INIT_LOCK = asyncio.Lock()
    return _BACKEND_INIT_LOCK


async def _close_backend_instance(backend: RateLimitBackend | None) -> None:
    if backend is None:
        return
    close_method = getattr(backend, "close", None)
    if close_method is None:
        return
    result = close_method()
    if inspect.isawaitable(result):
        await result


async def get_rate_limit_backend() -> RateLimitBackend:
    """Return the active rate limit backend, initializing on first call."""
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND

    async with _get_backend_init_lock():
        if _BACKEND is not None:
            return _BACKEND

        redis_url = os.environ.get("REDIS_URL", "").strip()
        require_redis = _is_truthy_env("RATE_LIMIT_REQUIRE_REDIS")
        if redis_url:
            client = None
            try:
                redis_asyncio = importlib.import_module("redis.asyncio")
                socket_timeout_seconds = _get_redis_socket_timeout_seconds()
                operation_timeout_seconds = _get_redis_operation_timeout_seconds()
                client = redis_asyncio.Redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=socket_timeout_seconds,
                    socket_timeout=socket_timeout_seconds,
                    health_check_interval=_get_redis_health_check_interval_seconds(),
                )
                await asyncio.wait_for(client.ping(), timeout=operation_timeout_seconds)
                redis_backend = RedisRateLimitBackend(client)
                _BACKEND = _ResilientRedisBackend(
                    redis_backend,
                    strict=require_redis,
                    operation_timeout_seconds=operation_timeout_seconds,
                )
                RUNTIME_LOGGER.info(
                    "Rate limit backend initialized: redis",
                    extra={"event_name": "rate_limit_backend_init", "backend": "redis"},
                )
                return _BACKEND
            except Exception as exc:
                if client is not None:
                    aclose = getattr(client, "aclose", None)
                    if callable(aclose):
                        close_result = aclose()
                        if inspect.isawaitable(close_result):
                            await close_result
                if require_redis:
                    record_rate_limit_backend_degraded("strict_failure")
                    raise RuntimeError(
                        f"RATE_LIMIT_REQUIRE_REDIS=1 but Redis is unavailable: {exc}"
                    ) from exc
                record_rate_limit_backend_degraded("init_fallback")
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


async def shutdown_rate_limit_backend() -> None:
    """Explicitly close the active backend instance and clear singleton state."""
    global _BACKEND, _BACKEND_INIT_LOCK
    backend = _BACKEND
    _BACKEND = None
    _BACKEND_INIT_LOCK = None
    await _close_backend_instance(backend)


def reset_rate_limit_backend() -> None:
    """Force re-initialization on next get_rate_limit_backend() call (test only)."""
    global _BACKEND, _BACKEND_INIT_LOCK
    backend = _BACKEND
    _BACKEND = None
    _BACKEND_INIT_LOCK = None
    if backend is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_close_backend_instance(backend))
    else:
        loop.create_task(_close_backend_instance(backend))
