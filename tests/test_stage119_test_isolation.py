"""Stage 119: request-cache metrics must not leak between tests."""

from __future__ import annotations

from request_cache import REQUEST_CACHE


def test_request_cache_metrics_can_be_mutated():
    REQUEST_CACHE.metrics.hits = 7
    REQUEST_CACHE.metrics.misses = 3
    REQUEST_CACHE.metrics.invalidations = 2
    REQUEST_CACHE.metrics.evictions = 1

    assert REQUEST_CACHE.metrics.hits == 7
    assert REQUEST_CACHE.metrics.misses == 3
    assert REQUEST_CACHE.metrics.invalidations == 2
    assert REQUEST_CACHE.metrics.evictions == 1


def test_request_cache_metrics_are_reset_by_autouse_fixture():
    assert REQUEST_CACHE.metrics.hits == 0
    assert REQUEST_CACHE.metrics.misses == 0
    assert REQUEST_CACHE.metrics.invalidations == 0
    assert REQUEST_CACHE.metrics.evictions == 0
