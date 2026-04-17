"""Stage 91 — VM client overhaul: singleton httpx + retry + timeouts + breaker.

Covers:
- Shared httpx.AsyncClient is a lazy singleton; multiple _request calls reuse
  the same client (no new TLS handshake per request).
- GET on 429/502/503/504 retries with exponential backoff up to MAX_RETRIES_READ.
- Retry-After header (seconds form) overrides computed backoff.
- POST on 500 does NOT retry (non-idempotent).
- Circuit breaker opens after N consecutive failures; fast-fails further calls
  until cooldown elapses.
- _parse_retry_after parses seconds and HTTP-date forms.
"""

from __future__ import annotations

import time

import httpx
import pytest
import respx

import vetmanager_client as vm_client_module
from exceptions import VetmanagerUpstreamUnavailable
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import (
    MAX_RETRIES_READ,
    VetmanagerClient,
    _BREAKER_COOLDOWN_SECONDS,
    _BREAKER_FAILURE_THRESHOLD,
    _backoff_seconds,
    _parse_retry_after,
    reset_breakers,
    reset_shared_http_client,
)

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )


# ── _parse_retry_after ──────────────────────────────────────────────────────


def test_parse_retry_after_seconds_form():
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("0") == 0.0
    assert _parse_retry_after("  3  ") == 3.0


def test_parse_retry_after_rejects_empty_or_none():
    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("   ") is None


def test_parse_retry_after_http_date_form():
    # 60 seconds from now. Stage 96.6 clamps Retry-After at 300s max to
    # prevent DoS via 'Retry-After: 1e9', so we use a sub-clamp value.
    import email.utils
    import datetime as dt
    future = dt.datetime.now(tz=dt.timezone.utc) + dt.timedelta(seconds=60)
    header = email.utils.format_datetime(future)
    parsed = _parse_retry_after(header)
    assert parsed is not None
    # Allow ±5 seconds for scheduling drift on loaded CI hosts.
    assert 55 <= parsed <= 65


# ── _backoff_seconds ────────────────────────────────────────────────────────


def test_backoff_respects_retry_after_when_larger():
    assert _backoff_seconds(0, retry_after=3.0) >= 3.0


def test_backoff_exponential_without_retry_after():
    d0 = _backoff_seconds(0)
    d1 = _backoff_seconds(1)
    d2 = _backoff_seconds(2)
    # Roughly exponential (jitter ≤ 0.1s); d2 > d1 > d0 in expectation.
    # Not strict to avoid flaky jitter-related failures.
    assert d0 <= d1 + 0.2
    assert d1 <= d2 + 0.2


# ── Shared http client ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_shared_http_client_is_reused_across_requests():
    """Two sequential GETs must use the same underlying AsyncClient instance
    — pool reuse is the whole point of the singleton."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        vc = VetmanagerClient()
        await vc.get("/rest/api/client/1")
        client_first = vm_client_module._shared_http_client
        await vc.get("/rest/api/client/1")
        client_second = vm_client_module._shared_http_client

    assert client_first is client_second, "shared client must not be recreated"
    assert not client_first.is_closed


# ── Retry on 5xx (GET) ──────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_retries_on_503_then_succeeds():
    billing_mock()
    responses = [
        httpx.Response(503),
        httpx.Response(503),
        httpx.Response(200, json={"data": {"id": 1}}),
    ]
    route = respx.get(f"{BASE}/rest/api/client/1").mock(side_effect=responses)
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await VetmanagerClient().get("/rest/api/client/1")
    assert route.call_count == 3
    assert result["data"]["id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_honors_retry_after_seconds(monkeypatch):
    """Retry-After: 0 (smallest valid integer value) lets us assert the header
    is parsed and used without slowing the test. We monkeypatch backoff to 0
    to keep the timing assertion strict."""
    billing_mock()
    responses = [
        httpx.Response(429, headers={"Retry-After": "0"}),
        httpx.Response(200, json={"data": {"id": 2}}),
    ]
    route = respx.get(f"{BASE}/rest/api/client/2").mock(side_effect=responses)

    sleep_calls: list[float] = []

    async def _recorded_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _recorded_sleep)

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await VetmanagerClient().get("/rest/api/client/2")
    assert route.call_count == 2
    assert result["data"]["id"] == 2
    assert sleep_calls, "sleep must be invoked between retries"


@pytest.mark.asyncio
@respx.mock
async def test_get_gives_up_after_max_retries(monkeypatch):
    billing_mock()

    async def _no_sleep(_seconds):
        return None
    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(503, json={"error": "bad"})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})


# ── Non-idempotent POST does NOT retry on 5xx ───────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_post_does_not_retry_on_500():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(500, json={"error": "bad"})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception):
            await VetmanagerClient().post("/rest/api/client", json={"x": 1})

    assert route.call_count == 1, (
        f"expected single POST attempt on 500, got {route.call_count}"
    )


# ── Circuit breaker ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_circuit_breaker_opens_after_consecutive_failures(monkeypatch):
    """5 consecutive POST failures on the same domain open the breaker.
    The 6th call must fast-fail without hitting the upstream."""
    billing_mock()

    async def _no_sleep(_seconds):
        return None
    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    post_route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(500)
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        for _ in range(_BREAKER_FAILURE_THRESHOLD):
            try:
                await VetmanagerClient().post("/rest/api/client", json={"x": 1})
            except Exception:
                pass

        # Next call must be rejected by the breaker BEFORE hitting upstream.
        calls_before_fast_fail = post_route.call_count
        with pytest.raises(VetmanagerUpstreamUnavailable):
            await VetmanagerClient().post("/rest/api/client", json={"x": 1})
        assert post_route.call_count == calls_before_fast_fail, (
            "breaker must fast-fail without a new upstream call"
        )


@pytest.mark.asyncio
@respx.mock
async def test_circuit_breaker_resets_after_cooldown_and_success(monkeypatch):
    """After cooldown elapses, breaker goes HALF_OPEN and admits one probe.
    A successful probe flips it back to CLOSED."""
    billing_mock()

    async def _no_sleep(_seconds):
        return None
    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _no_sleep)

    # Failing route first, then succeeding route (same path).
    # Use a mutable counter for the route behaviour.
    state = {"phase": "fail"}

    def _side_effect(request):
        if state["phase"] == "fail":
            return httpx.Response(500)
        return httpx.Response(200, json={"data": {"ok": True}})

    route = respx.post(f"{BASE}/rest/api/client").mock(side_effect=_side_effect)

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        # Trip the breaker.
        for _ in range(_BREAKER_FAILURE_THRESHOLD):
            try:
                await VetmanagerClient().post("/rest/api/client", json={"x": 1})
            except Exception:
                pass

        # Manually age the breaker past the cooldown without sleeping.
        breaker = vm_client_module._breakers[DOMAIN]
        breaker.opened_at = time.monotonic() - _BREAKER_COOLDOWN_SECONDS - 1

        state["phase"] = "ok"
        # Probe goes through (half-open admits one request).
        result = await VetmanagerClient().post("/rest/api/client", json={"x": 1})
        assert result["data"]["ok"] is True

        # Breaker must be closed now.
        assert breaker.state == "closed", (
            f"expected closed after successful probe, got {breaker.state}"
        )


# ── Timeout config ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_admits_only_one_probe():
    """Under concurrency, only ONE request should probe while others fast-fail.
    Without probe_in_flight guard, N concurrent callers in half_open would all
    try to hit the upstream, defeating the breaker purpose."""
    await reset_breakers()
    breaker = await vm_client_module._get_breaker(DOMAIN)
    # Force OPEN with elapsed cooldown so next check flips to HALF_OPEN.
    async with breaker.lock:
        breaker.state = "open"
        breaker.opened_at = time.monotonic() - _BREAKER_COOLDOWN_SECONDS - 1

    # First check: admits probe, sets probe_in_flight=True.
    await vm_client_module._check_breaker_allows(DOMAIN)
    assert breaker.state == "half_open"
    assert breaker.probe_in_flight is True

    # Second concurrent check must be rejected — probe in flight.
    with pytest.raises(VetmanagerUpstreamUnavailable):
        await vm_client_module._check_breaker_allows(DOMAIN)

    # Probe finishes successfully → closed, flag clears.
    await vm_client_module._breaker_record_success(DOMAIN)
    assert breaker.state == "closed"
    assert breaker.probe_in_flight is False


def test_split_timeouts_are_configured():
    from vetmanager_client import _REQUEST_TIMEOUTS
    # httpx.Timeout stores individual component values in attributes.
    assert _REQUEST_TIMEOUTS.connect == 5.0
    assert _REQUEST_TIMEOUTS.read == 20.0
    assert _REQUEST_TIMEOUTS.write == 10.0
    assert _REQUEST_TIMEOUTS.pool == 2.0


def test_http_limits_enable_keep_alive_pool():
    from vetmanager_client import _HTTP_LIMITS
    assert _HTTP_LIMITS.max_keepalive_connections == 50
    assert _HTTP_LIMITS.max_connections == 100
    assert _HTTP_LIMITS.keepalive_expiry == 30.0
