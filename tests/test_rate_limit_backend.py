"""Tests for pluggable rate limit backends."""

import time

import pytest

from rate_limit_backend import (
    InMemoryRateLimitBackend,
    RedisRateLimitBackend,
    get_rate_limit_backend,
    reset_rate_limit_backend,
)


# ── In-memory backend ────────────────────────────────────────────────────────


def test_in_memory_count_starts_at_zero():
    backend = InMemoryRateLimitBackend()
    assert backend.count_in_window("ns", "key", window_seconds=60) == 0


def test_in_memory_record_hit_increments_count():
    backend = InMemoryRateLimitBackend()
    backend.record_hit("ns", "key", window_seconds=60)
    backend.record_hit("ns", "key", window_seconds=60)
    assert backend.count_in_window("ns", "key", window_seconds=60) == 2


def test_in_memory_clear_removes_state():
    backend = InMemoryRateLimitBackend()
    backend.record_hit("ns", "key", window_seconds=60)
    backend.clear("ns", "key")
    assert backend.count_in_window("ns", "key", window_seconds=60) == 0


def test_in_memory_reset_all_clears_all_namespaces():
    backend = InMemoryRateLimitBackend()
    backend.record_hit("ns1", "key1", window_seconds=60)
    backend.record_hit("ns2", "key2", window_seconds=60)
    backend.reset_all()
    assert backend.count_in_window("ns1", "key1", window_seconds=60) == 0
    assert backend.count_in_window("ns2", "key2", window_seconds=60) == 0


def test_in_memory_window_expires_old_entries():
    backend = InMemoryRateLimitBackend()
    # window=1 second; sleep then check that old entry is pruned
    backend.record_hit("ns", "key", window_seconds=1)
    time.sleep(1.1)
    assert backend.count_in_window("ns", "key", window_seconds=1) == 0


def test_in_memory_isolated_per_namespace():
    backend = InMemoryRateLimitBackend()
    backend.record_hit("login", "user1", window_seconds=60)
    assert backend.count_in_window("login", "user1", window_seconds=60) == 1
    assert backend.count_in_window("register", "user1", window_seconds=60) == 0


# ── Redis backend (via fakeredis) ────────────────────────────────────────────


def test_redis_backend_count_starts_at_zero():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    assert backend.count_in_window("ns", "key", window_seconds=60) == 0


def test_redis_backend_record_and_count():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    backend.record_hit("ns", "key", window_seconds=60)
    backend.record_hit("ns", "key", window_seconds=60)
    backend.record_hit("ns", "key", window_seconds=60)
    assert backend.count_in_window("ns", "key", window_seconds=60) == 3


def test_redis_backend_clear_removes_zset():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    backend.record_hit("ns", "key", window_seconds=60)
    backend.clear("ns", "key")
    assert backend.count_in_window("ns", "key", window_seconds=60) == 0


def test_redis_backend_window_pruning():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    backend = RedisRateLimitBackend(client)
    backend.record_hit("ns", "key", window_seconds=1)
    time.sleep(1.1)
    assert backend.count_in_window("ns", "key", window_seconds=1) == 0


def test_redis_backend_reset_all_only_clears_own_prefix():
    fakeredis = pytest.importorskip("fakeredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    client.set("other:key", "should-survive")
    backend = RedisRateLimitBackend(client)
    backend.record_hit("ns", "key", window_seconds=60)
    backend.reset_all()
    assert backend.count_in_window("ns", "key", window_seconds=60) == 0
    assert client.get("other:key") == "should-survive"


# ── Factory selection ────────────────────────────────────────────────────────


def test_factory_default_is_in_memory(monkeypatch):
    monkeypatch.delenv("REDIS_URL", raising=False)
    reset_rate_limit_backend()
    backend = get_rate_limit_backend()
    assert isinstance(backend, InMemoryRateLimitBackend)
    reset_rate_limit_backend()


def test_factory_falls_back_to_in_memory_when_redis_unreachable(monkeypatch):
    """Unreachable REDIS_URL should fall back to in-memory with warning, not crash."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")  # invalid port
    monkeypatch.delenv("RATE_LIMIT_REQUIRE_REDIS", raising=False)
    reset_rate_limit_backend()
    backend = get_rate_limit_backend()
    assert isinstance(backend, InMemoryRateLimitBackend)
    reset_rate_limit_backend()


def test_factory_fail_fast_when_require_redis_set(monkeypatch):
    """RATE_LIMIT_REQUIRE_REDIS=1 must raise when Redis is unreachable."""
    monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:1/0")
    monkeypatch.setenv("RATE_LIMIT_REQUIRE_REDIS", "1")
    reset_rate_limit_backend()
    with pytest.raises(RuntimeError, match="RATE_LIMIT_REQUIRE_REDIS"):
        get_rate_limit_backend()
    reset_rate_limit_backend()


# ── Resilient Redis backend (mid-operation fallback) ────────────────────────


class _BrokenRedis:
    def zremrangebyscore(self, *_, **__):
        raise RuntimeError("connection lost")

    def zcard(self, *_, **__):
        raise RuntimeError("connection lost")

    def zadd(self, *_, **__):
        raise RuntimeError("connection lost")

    def expire(self, *_, **__):
        raise RuntimeError("connection lost")

    def pipeline(self):
        return self

    def execute(self):
        raise RuntimeError("connection lost")

    def delete(self, *_, **__):
        raise RuntimeError("connection lost")

    def scan_iter(self, *_, **__):
        raise RuntimeError("connection lost")


def test_resilient_redis_falls_back_to_in_memory_on_runtime_error():
    """When Redis raises mid-operation in non-strict mode, degrade to in-memory."""
    from rate_limit_backend import _ResilientRedisBackend

    redis_backend = RedisRateLimitBackend(_BrokenRedis())
    resilient = _ResilientRedisBackend(redis_backend, strict=False)

    # All operations should not raise
    resilient.record_hit("ns", "key", window_seconds=60)
    resilient.record_hit("ns", "key", window_seconds=60)
    # Fallback in-memory should now have the hits
    assert resilient.count_in_window("ns", "key", window_seconds=60) == 2
    resilient.clear("ns", "key")
    assert resilient.count_in_window("ns", "key", window_seconds=60) == 0


def test_resilient_redis_strict_mode_propagates_errors():
    """In strict mode, Redis errors must propagate (fail closed)."""
    from rate_limit_backend import _ResilientRedisBackend

    redis_backend = RedisRateLimitBackend(_BrokenRedis())
    resilient = _ResilientRedisBackend(redis_backend, strict=True)

    with pytest.raises(RuntimeError, match="connection lost"):
        resilient.record_hit("ns", "key", window_seconds=60)
    with pytest.raises(RuntimeError, match="connection lost"):
        resilient.count_in_window("ns", "key", window_seconds=60)


