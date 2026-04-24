"""Stage 105.2 regressions: breaker counts 1 failure per logical call (not per retry)
and re-checks breaker before every retry attempt.

Was: a single failing GET with MAX_RETRIES_READ=3 caused 4 `_breaker_record_failure`
calls (one per attempt), tripping the circuit after 1 real request instead of 4 at
BREAKER_FAILURE_THRESHOLD=5. Fix: record failure once post-exhaustion; also re-check
breaker before each retry so a concurrently-tripped circuit aborts the retry loop.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from exceptions import VetmanagerError, VetmanagerTimeoutError, VetmanagerUpstreamUnavailable
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient, get_breaker_state

DOMAIN = "breaker-amp-clinic"
API_KEY = "breaker-amp-key"
BASE = f"https://{DOMAIN}.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="breaker-amp-token",
        bearer_token_id=1,
        connection_id=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_breaker_one_failure_per_logical_call(monkeypatch):
    """Один GET с max_retries=3, который стабильно таймаутит, должен увеличить
    `consecutive_failures` breaker'а ровно на 1 (не на 4)."""
    # Stage 105.2: no sleep, чтобы 4 retry не занимали ~20+ секунд на fake timeouts.
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)
    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    billing_mock()
    respx.get(f"{BASE}/rest/api/client/1").mock(side_effect=httpx.TimeoutException("boom"))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerTimeoutError):
            await VetmanagerClient().get("/rest/api/client/1")

    state = get_breaker_state(DOMAIN)
    assert state is not None, "breaker state should exist for the domain"
    assert state["consecutive_failures"] == 1, (
        f"expected 1 breaker failure per logical call, got {state['consecutive_failures']} "
        f"(would be 4 under per-attempt counting — the regression this test guards)"
    )


@pytest.mark.asyncio
@respx.mock
async def test_retry_aborts_when_breaker_trips_mid_loop(monkeypatch):
    """Если breaker OPEN'ит *между* retry iterations (первый attempt упал,
    другой concurrent caller насчитал порог во время backoff sleep), то
    re-check в начале `attempt > 0` iteration должен поймать OPEN и сразу
    raise VetmanagerUpstreamUnavailable — retry loop не делает второй HTTP-вызов.
    """
    from vetmanager_client import force_breaker_open

    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)

    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client/2").mock(
        side_effect=httpx.TimeoutException("boom")
    )

    # Хук на asyncio.sleep: отслеживаем момент, когда retry loop засыпает
    # с положительным backoff (>=0.05s — это точно не _pace_requests, тот
    # спит <0.05s). При первом таком backoff-sleep эмулируем «другой
    # concurrent caller насчитал BREAKER_FAILURE_THRESHOLD» и открываем
    # breaker. Следующая iteration ре-чекает breaker и abort'ит.
    tripped = {"done": False}

    async def _sleep_trips_breaker_on_backoff(delay: float) -> None:
        if not tripped["done"] and delay >= 0.05:
            tripped["done"] = True
            await force_breaker_open(DOMAIN)

    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _sleep_trips_breaker_on_backoff)

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerUpstreamUnavailable):
            await VetmanagerClient().get("/rest/api/client/2")

    # Только первый attempt должен был сделать HTTP-вызов.
    # На iteration 2 re-check breaker'а отловил OPEN до client.request().
    assert route.call_count == 1, (
        f"expected exactly 1 HTTP call before breaker trip aborts retries, "
        f"got {route.call_count}"
    )
    assert tripped["done"], "breaker trip hook should have fired during backoff"
    state = get_breaker_state(DOMAIN)
    assert state is not None
    assert state["consecutive_failures"] == 0, (
        "retry-time breaker denial must not be counted as a fresh upstream failure"
    )


async def _no_sleep(_: float) -> None:
    return None
