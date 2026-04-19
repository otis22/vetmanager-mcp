"""Stage 115: real concurrency tests — breaker amplification + pool singleton."""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from exceptions import VetmanagerError, VetmanagerTimeoutError, VetmanagerUpstreamUnavailable
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient
from vm_transport.breaker import breaker_failure_threshold, get_breaker_state, reset_breakers
from vm_transport.pool import get_shared_http_client, reset_shared_http_client


DOMAIN = "conclinic"
API_KEY = "k"
BASE = f"https://{DOMAIN}.vetmanager.cloud"
N_CONCURRENT = 8


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _bearer_patch():
    return patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="t", bearer_token_id=1, connection_id=1,
    )


# ── 115.1: breaker under true concurrency ──────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_breaker_opens_under_concurrent_failures_without_amplification(monkeypatch):
    """N concurrent GETs all timeout → breaker MUST open within
    threshold + small buffer failures, not N × max_retries worth.

    Regression for stage 105 amplification: before the fix, each caller
    recorded its own (failed) attempt, so 8 callers × 3 retries = 24
    breaker failures, opening breaker in a cascade that amplified the
    upstream incident. Fix = one failure per logical call. This test
    exercises REAL asyncio.gather concurrency instead of sequential mocks.
    """
    # Zero backoff so retries exhaust quickly under concurrency.
    async def _no_sleep(_):
        return None
    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)

    await reset_breakers()
    await reset_shared_http_client()

    _billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        side_effect=httpx.TimeoutException("concurrent boom")
    )

    headers_patch, runtime_patch = _bearer_patch()
    # Barrier ensures all N coroutines reach client.request() together so
    # admission races happen at the upstream boundary, not at task-start
    # scheduling. Addresses Codex finding on non-synchronized start.
    start_barrier = asyncio.Event()
    with headers_patch, runtime_patch:
        async def _one_call():
            await start_barrier.wait()
            try:
                await VetmanagerClient().get("/rest/api/client", params={"limit": 1})
            except (VetmanagerTimeoutError, VetmanagerError, VetmanagerUpstreamUnavailable):
                pass

        tasks = [asyncio.create_task(_one_call()) for _ in range(N_CONCURRENT)]
        # Yield so every task enters barrier.wait() before we release.
        await asyncio.sleep(0)
        start_barrier.set()
        await asyncio.gather(*tasks)

    state = get_breaker_state(DOMAIN)
    assert state is not None, "breaker registry must have domain after concurrent calls"

    threshold = breaker_failure_threshold()
    # Amplification = record_failure called max_retries × N_CONCURRENT times.
    # Stage 105 fix = one failure per logical call = N_CONCURRENT at worst.
    # Allow buffer for probes slipping through the half-open admission race.
    assert state["consecutive_failures"] <= N_CONCURRENT + 2, (
        f"Amplification regression: concurrent_failures={state['consecutive_failures']} "
        f"expected <= N_CONCURRENT+2={N_CONCURRENT + 2} (threshold={threshold})"
    )
    # Breaker MUST be OPEN after threshold crossed under sustained failure
    # flood. "half_open" would mean cooldown elapsed mid-test which can't
    # happen given test duration < BREAKER_COOLDOWN_SECONDS (30s default).
    assert state["state"] == "open", (
        f"breaker should be OPEN after sustained concurrent failures, got {state}"
    )

    await reset_breakers()
    await reset_shared_http_client()


# ── 115.2: shared pool singleton under concurrency ─────────────────────────


@pytest.mark.asyncio
async def test_get_shared_http_client_returns_same_instance_under_concurrency():
    """N concurrent calls → same AsyncClient object identity. No N-1
    orphaned clients leaking sockets."""
    await reset_shared_http_client()
    try:
        clients = await asyncio.gather(*[
            get_shared_http_client() for _ in range(N_CONCURRENT)
        ])
        first = clients[0]
        assert all(c is first for c in clients), (
            "concurrent get_shared_http_client must return the same instance"
        )
        assert not first.is_closed
    finally:
        await reset_shared_http_client()
