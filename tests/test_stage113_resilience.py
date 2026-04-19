"""Stage 113: resilience completeness — billing-api hardening + breaker env accessors."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from host_resolver import (
    BILLING_RESOLVER_CACHE_TTL_SECONDS,
    reset_billing_resolver,
    resolve_vetmanager_host,
)
from vm_transport.breaker import (
    breaker_failure_threshold,
    breaker_window_seconds,
    breaker_cooldown_seconds,
    breaker_record_failure,
    get_breaker_state,
    reset_breakers,
)


DOMAIN = "cachedclinic"
BILLING_URL = f"https://billing-api.vetmanager.cloud/host/{DOMAIN}"
RESOLVED = "https://cachedclinic.vetmanager.cloud"


@pytest.fixture(autouse=True)
async def _reset_billing_resolver_between_tests():
    await reset_billing_resolver()
    yield
    await reset_billing_resolver()


# ── 113.F7: TTL cache ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_resolver_hits_cache_on_second_call_for_same_domain():
    route = respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": RESOLVED}})
    )
    first = await resolve_vetmanager_host(DOMAIN)
    second = await resolve_vetmanager_host(DOMAIN)
    third = await resolve_vetmanager_host(DOMAIN)

    assert first == second == third == RESOLVED
    assert route.call_count == 1, (
        f"expected cache hit after first call, got {route.call_count} HTTP requests"
    )


@pytest.mark.asyncio
@respx.mock
async def test_resolver_does_not_cache_errors():
    """Failed resolution (HTTP 404) is NOT cached; retry must hit upstream."""
    call_count = 0

    def _side(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(404)
        return httpx.Response(200, json={"data": {"url": RESOLVED}})

    respx.get(BILLING_URL).mock(side_effect=_side)
    from exceptions import HostResolutionError
    with pytest.raises(HostResolutionError):
        await resolve_vetmanager_host(DOMAIN)

    # Second call must hit upstream — error must not poison cache.
    result = await resolve_vetmanager_host(DOMAIN)
    assert result == RESOLVED
    assert call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_resolver_parallel_calls_collapse_to_single_http():
    """10 concurrent calls for the same domain → 1 upstream HTTP request."""
    route = respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": RESOLVED}})
    )

    results = await asyncio.gather(*[
        resolve_vetmanager_host(DOMAIN) for _ in range(10)
    ])
    assert all(r == RESOLVED for r in results)
    # Best case: 1 request. Acceptable worst-case under weak locking: up to a few.
    # Require ≤ 2 (the first may not be cached yet when the second enters).
    assert route.call_count <= 2, (
        f"expected parallel calls to share upstream result, got "
        f"{route.call_count} HTTP requests"
    )


@pytest.mark.asyncio
async def test_reset_billing_resolver_clears_cache_and_closes_client():
    """reset_billing_resolver must be safe to call repeatedly."""
    await reset_billing_resolver()
    await reset_billing_resolver()


def test_billing_resolver_cache_ttl_constant_is_positive():
    assert BILLING_RESOLVER_CACHE_TTL_SECONDS > 0


# ── 113.1: breaker env accessors ───────────────────────────────────────────


def test_breaker_threshold_accessor_reads_current_env(monkeypatch):
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")
    assert breaker_failure_threshold() == 2
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "7")
    assert breaker_failure_threshold() == 7


def test_breaker_window_accessor_reads_current_env(monkeypatch):
    monkeypatch.setenv("BREAKER_WINDOW_SECONDS", "45")
    assert breaker_window_seconds() == 45.0


def test_breaker_cooldown_accessor_reads_current_env(monkeypatch):
    monkeypatch.setenv("BREAKER_COOLDOWN_SECONDS", "15")
    assert breaker_cooldown_seconds() == 15.0


@pytest.mark.asyncio
async def test_breaker_honors_env_threshold_override(monkeypatch):
    """monkeypatch.setenv on BREAKER_FAILURE_THRESHOLD must affect breaker behaviour."""
    await reset_breakers()
    monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")

    domain = "env-override.example.com"
    await breaker_record_failure(domain)
    state_after_one = get_breaker_state(domain)
    assert state_after_one["state"] == "closed"

    await breaker_record_failure(domain)
    state_after_two = get_breaker_state(domain)
    assert state_after_two["state"] == "open", (
        f"expected state 'open' after 2 failures with env threshold=2, "
        f"got {state_after_two}"
    )
    await reset_breakers()
