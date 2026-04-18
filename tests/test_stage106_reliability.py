"""Stage 106 reliability fixes regressions.

106.1 F2: asyncio.CancelledError (and other unexpected exceptions) used to wedge
       breaker HALF_OPEN probe_in_flight=True forever. Fix: try/finally around
       retry loop records failure (clearing probe flag) if no normal branch ran
       its breaker hook.

106.2 F3: concurrent first-init of the per-loop HTTP client could create two
       `AsyncClient` instances, orphaning one. Fix: use `_shared_http_client_lock`
       with double-check pattern around construction.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from exceptions import VetmanagerUpstreamUnavailable
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import (
    VetmanagerClient,
    force_breaker_open,
    get_breaker_state,
)

DOMAIN = "reliability-clinic"
API_KEY = "reliability-key"
BASE = f"https://{DOMAIN}.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="reliability-token",
        bearer_token_id=1,
        connection_id=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_cancelled_probe_clears_breaker_probe_in_flight(monkeypatch):
    """F2: task cancellation during HALF_OPEN probe must clear probe_in_flight.

    Scenario: breaker is OPEN and cooldown has elapsed; _check_breaker_allows
    transitions to HALF_OPEN with probe_in_flight=True. Before the HTTP round
    completes, the enclosing task is cancelled. The finally in _request should
    call _breaker_record_failure, clearing probe_in_flight so subsequent
    requests aren't fast-failed with "probe already in flight" forever.
    """
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)

    # Force breaker OPEN with elapsed cooldown — next check transitions to HALF_OPEN.
    await force_breaker_open(DOMAIN, cooldown_elapsed=True)
    state_before = get_breaker_state(DOMAIN)
    assert state_before["state"] == "open", state_before

    billing_mock()

    # The mock side_effect raises CancelledError from inside httpx — simulates
    # task cancellation (or any unexpected exception that our except branches
    # don't handle) AFTER _check_breaker_allows set probe_in_flight=True.
    async def _raise_cancel(request):
        raise asyncio.CancelledError()

    respx.get(f"{BASE}/rest/api/client/1").mock(side_effect=_raise_cancel)

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(asyncio.CancelledError):
            await VetmanagerClient().get("/rest/api/client/1")

    # After cancellation, breaker state should NOT be wedged in HALF_OPEN with
    # probe_in_flight=True — the finally clause should have recorded failure,
    # which in HALF_OPEN state transitions back to OPEN with probe_in_flight=False.
    state_after = get_breaker_state(DOMAIN)
    assert state_after is not None
    assert state_after["probe_in_flight"] is False, (
        f"probe_in_flight should be cleared after cancellation; state={state_after}"
    )


@pytest.mark.asyncio
async def test_concurrent_first_init_creates_single_pool_client():
    """F3: N concurrent get_shared_http_client() calls on a fresh loop must
    settle on ONE AsyncClient instance, not leak N-1 orphans.
    """
    # reset_shared_http_client runs via conftest fixture; start clean.
    from vm_transport.pool import (
        _shared_http_clients,
        current_loop_key,
        get_shared_http_client,
    )

    key = current_loop_key()
    _shared_http_clients.pop(key, None)

    # Fire 8 concurrent first-init calls.
    clients = await asyncio.gather(*[get_shared_http_client() for _ in range(8)])

    # All 8 callers must see the SAME client instance.
    first = clients[0]
    assert all(c is first for c in clients), (
        "concurrent first-init returned different AsyncClient instances "
        "(race — lock missing)"
    )

    # Dict should contain exactly one entry for this loop.
    assert key in _shared_http_clients
    assert _shared_http_clients[key] is first
