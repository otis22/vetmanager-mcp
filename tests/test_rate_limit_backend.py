"""Tests for pluggable async rate limit backends."""

from __future__ import annotations

import asyncio
import sys
import time
import types

import pytest

from rate_limit_backend import (
    InMemoryRateLimitBackend,
    RedisRateLimitBackend,
    get_rate_limit_backend,
    reset_rate_limit_backend,
)
from web_security import check_rate_limit


# ── In-memory backend ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_in_memory_count_starts_at_zero():
    backend = InMemoryRateLimitBackend()
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_in_memory_record_hit_increments_count():
    backend = InMemoryRateLimitBackend()
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.record_hit("ns", "key", window_seconds=60)
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 2


@pytest.mark.asyncio
async def test_in_memory_consume_hit_enforces_limit():
    backend = InMemoryRateLimitBackend()
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (1, True)
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (2, True)
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (2, False)


@pytest.mark.asyncio
async def test_in_memory_clear_removes_state():
    backend = InMemoryRateLimitBackend()
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.clear("ns", "key")
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_in_memory_reset_all_clears_all_namespaces():
    backend = InMemoryRateLimitBackend()
    await backend.record_hit("ns1", "key1", window_seconds=60)
    await backend.record_hit("ns2", "key2", window_seconds=60)
    await backend.reset_all()
    assert await backend.count_in_window("ns1", "key1", window_seconds=60) == 0
    assert await backend.count_in_window("ns2", "key2", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_in_memory_window_expires_old_entries():
    backend = InMemoryRateLimitBackend()
    await backend.record_hit("ns", "key", window_seconds=1)
    await asyncio.sleep(1.1)
    assert await backend.count_in_window("ns", "key", window_seconds=1) == 0


@pytest.mark.asyncio
async def test_in_memory_isolated_per_namespace():
    backend = InMemoryRateLimitBackend()
    await backend.record_hit("login", "user1", window_seconds=60)
    assert await backend.count_in_window("login", "user1", window_seconds=60) == 1
    assert await backend.count_in_window("register", "user1", window_seconds=60) == 0


# ── Redis backend (via fakeredis) ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_redis_backend_count_starts_at_zero():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_redis_backend_record_and_count():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.record_hit("ns", "key", window_seconds=60)
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 3


@pytest.mark.asyncio
async def test_redis_backend_consume_hit_enforces_limit():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (1, True)
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (2, True)
    assert await backend.consume_hit("ns", "key", limit=2, window_seconds=60) == (2, False)


@pytest.mark.asyncio
async def test_redis_backend_clear_removes_zset():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.clear("ns", "key")
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_redis_backend_window_pruning():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    await backend.record_hit("ns", "key", window_seconds=1)
    await asyncio.sleep(1.1)
    assert await backend.count_in_window("ns", "key", window_seconds=1) == 0


@pytest.mark.asyncio
async def test_redis_backend_reset_all_only_clears_own_prefix():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeAsyncRedis(decode_responses=True)
    await client.set("other:key", "should-survive")
    backend = RedisRateLimitBackend(client)
    await backend.record_hit("ns", "key", window_seconds=60)
    await backend.reset_all()
    assert await backend.count_in_window("ns", "key", window_seconds=60) == 0
    assert await client.get("other:key") == "should-survive"


# ── Factory selection ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_factory_default_is_in_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_rate_limit_backend()
    backend = await get_rate_limit_backend()
    assert isinstance(backend, InMemoryRateLimitBackend)
    reset_rate_limit_backend()


@pytest.mark.asyncio
async def test_factory_falls_back_to_in_memory_when_redis_unreachable(monkeypatch):
    """Unreachable REDIS_URL should fall back to in-memory with warning, not crash."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.delenv("RATE_LIMIT_REQUIRE_REDIS", raising=False)
    reset_rate_limit_backend()
    backend = await get_rate_limit_backend()
    assert isinstance(backend, InMemoryRateLimitBackend)
    reset_rate_limit_backend()


@pytest.mark.asyncio
async def test_factory_fail_fast_when_require_redis_set(monkeypatch):
    """RATE_LIMIT_REQUIRE_REDIS=1 must raise when Redis is unreachable."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("RATE_LIMIT_REQUIRE_REDIS", "1")
    reset_rate_limit_backend()
    with pytest.raises(RuntimeError, match="RATE_LIMIT_REQUIRE_REDIS"):
        await get_rate_limit_backend()
    reset_rate_limit_backend()


@pytest.mark.asyncio
async def test_factory_uses_redis_asyncio_client(monkeypatch):
    calls: list[tuple[str, object]] = []

    class _FakeRedisClient:
        async def ping(self):
            calls.append(("ping", None))

    class _FakeRedisClass:
        @staticmethod
        def from_url(url, decode_responses=True):
            calls.append(("from_url", url, decode_responses))
            return _FakeRedisClient()

    fake_asyncio_module = types.SimpleNamespace(Redis=_FakeRedisClass)
    fake_redis_module = types.SimpleNamespace(asyncio=fake_asyncio_module)

    monkeypatch.setenv("REDIS_URL", "redis://example.test:6379/0")
    monkeypatch.delenv("RATE_LIMIT_REQUIRE_REDIS", raising=False)
    monkeypatch.setitem(sys.modules, "redis", fake_redis_module)
    monkeypatch.setitem(sys.modules, "redis.asyncio", fake_asyncio_module)
    reset_rate_limit_backend()

    backend = await get_rate_limit_backend()

    assert type(backend).__name__ == "_ResilientRedisBackend"
    assert calls == [
        ("from_url", "redis://example.test:6379/0", True),
        ("ping", None),
    ]
    reset_rate_limit_backend()


# ── Resilient Redis backend (mid-operation fallback) ────────────────────────


class _BrokenRedis:
    async def zremrangebyscore(self, *_, **__):
        raise RuntimeError("connection lost")

    async def zcard(self, *_, **__):
        raise RuntimeError("connection lost")

    async def zadd(self, *_, **__):
        raise RuntimeError("connection lost")

    async def expire(self, *_, **__):
        raise RuntimeError("connection lost")

    def pipeline(self):
        return self

    async def execute(self):
        raise RuntimeError("connection lost")

    async def delete(self, *_, **__):
        raise RuntimeError("connection lost")

    async def scan_iter(self, *_, **__):
        raise RuntimeError("connection lost")
        yield None


@pytest.mark.asyncio
async def test_resilient_redis_falls_back_to_in_memory_on_runtime_error():
    """When Redis raises mid-operation in non-strict mode, degrade to in-memory."""
    from rate_limit_backend import _ResilientRedisBackend

    redis_backend = RedisRateLimitBackend(_BrokenRedis())
    resilient = _ResilientRedisBackend(redis_backend, strict=False)

    await resilient.record_hit("ns", "key", window_seconds=60)
    await resilient.record_hit("ns", "key", window_seconds=60)
    assert await resilient.count_in_window("ns", "key", window_seconds=60) == 2
    await resilient.clear("ns", "key")
    assert await resilient.count_in_window("ns", "key", window_seconds=60) == 0


@pytest.mark.asyncio
async def test_resilient_redis_strict_mode_propagates_errors():
    """In strict mode, Redis errors must propagate (fail closed)."""
    from rate_limit_backend import _ResilientRedisBackend

    redis_backend = RedisRateLimitBackend(_BrokenRedis())
    resilient = _ResilientRedisBackend(redis_backend, strict=True)

    with pytest.raises(RuntimeError, match="connection lost"):
        await resilient.record_hit("ns", "key", window_seconds=60)
    with pytest.raises(RuntimeError, match="connection lost"):
        await resilient.count_in_window("ns", "key", window_seconds=60)


# ── Concurrency / interleaving ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_check_rate_limit_calls_backend_interleaved(monkeypatch):
    from web_security import RateLimitError

    class _SlowBackend:
        def __init__(self) -> None:
            self.active = 0
            self.max_active = 0

        async def count_in_window(self, namespace: str, key: str, *, window_seconds: int) -> int:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
            await asyncio.sleep(0.05)
            self.active -= 1
            return 0

        async def record_hit(self, namespace: str, key: str, *, window_seconds: int) -> None:
            return None

        async def clear(self, namespace: str, key: str) -> None:
            return None

        async def reset_all(self) -> None:
            return None

    backend = _SlowBackend()

    async def _fake_get_backend():
        return backend

    monkeypatch.setattr("web_security.get_rate_limit_backend", _fake_get_backend)

    started = time.perf_counter()
    await asyncio.gather(
        check_rate_limit("login", "a", limit=10, window_seconds=60),
        check_rate_limit("login", "b", limit=10, window_seconds=60),
        check_rate_limit("login", "c", limit=10, window_seconds=60),
    )
    elapsed = time.perf_counter() - started

    assert backend.max_active >= 2
    assert elapsed < 0.12, f"expected interleaving, got serial latency {elapsed:.3f}s"


@pytest.mark.asyncio
async def test_in_memory_consume_hit_is_atomic_under_concurrency():
    backend = InMemoryRateLimitBackend()
    results = await asyncio.gather(
        *[
            backend.consume_hit("login", "user@example.com", limit=3, window_seconds=60)
            for _ in range(6)
        ]
    )
    allowed = sum(1 for _, ok in results if ok)
    rejected = sum(1 for _, ok in results if not ok)
    assert allowed == 3
    assert rejected == 3
