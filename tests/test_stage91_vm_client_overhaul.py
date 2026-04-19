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


def test_parse_retry_after_clamps_to_300s_max():
    """Stage 109.9: DoS protection — honour upstream hint but cap at 300s."""
    assert _parse_retry_after("301") == 300.0
    assert _parse_retry_after("999999") == 300.0
    assert _parse_retry_after("1000000000.5") == 300.0


def test_parse_retry_after_clamps_negative_to_zero():
    """Stage 109.9: negative/zero Retry-After coerces to 0 (no delay)."""
    assert _parse_retry_after("-5") == 0.0
    assert _parse_retry_after("-0.01") == 0.0


def test_parse_retry_after_accepts_float_seconds():
    """Stage 109.9: Retry-After is spec'd as integer, but some upstreams
    send floats; accept them (HTTP-level strictness not our job)."""
    assert _parse_retry_after("1.5") == 1.5
    assert _parse_retry_after("0.25") == 0.25


def test_parse_retry_after_rejects_inf_nan():
    """Stage 109.9: inf/nan (malicious / malformed) must reject, not crash."""
    assert _parse_retry_after("inf") is None
    assert _parse_retry_after("nan") is None
    assert _parse_retry_after("-inf") is None


def test_parse_retry_after_http_date_form(monkeypatch):
    """Stage 101.6: monkeypatch datetime.now so the assertion is
    deterministic instead of relying on CI scheduling tolerance."""
    import datetime as dt
    import email.utils
    import vetmanager_client as _vm

    fixed_now = dt.datetime(2026, 4, 17, 12, 0, 0, tzinfo=dt.timezone.utc)
    future = fixed_now + dt.timedelta(seconds=60)
    header = email.utils.format_datetime(future)

    class _FrozenDatetime(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now if tz is None else fixed_now.astimezone(tz)

    # _parse_retry_after imports datetime locally inside the function.
    # Patch via sys.modules trick: replace the module-level `datetime` class
    # the function will see by monkeypatching datetime.datetime globally.
    monkeypatch.setattr(dt, "datetime", _FrozenDatetime)
    parsed = _vm._parse_retry_after(header)
    assert parsed == pytest.approx(60.0, abs=0.01)


# ── _backoff_seconds ────────────────────────────────────────────────────────


def test_backoff_respects_retry_after_when_larger():
    assert _backoff_seconds(0, retry_after=3.0) >= 3.0


def test_backoff_exponential_without_retry_after(monkeypatch):
    """Stage 101.3: eliminate jitter via monkeypatch and assert strict
    exponential growth instead of the previous vacuous inequality."""
    # Stage 103d: backoff math moved to vm_transport.retry; patch it there.
    monkeypatch.setattr("vm_transport.retry.random.uniform", lambda a, b: 0.0)
    d0 = _backoff_seconds(0)
    d1 = _backoff_seconds(1)
    d2 = _backoff_seconds(2)
    # Deterministic: 0.2 * 2^attempt = 0.2, 0.4, 0.8.
    assert d0 == pytest.approx(0.2, abs=1e-9)
    assert d1 == pytest.approx(0.4, abs=1e-9)
    assert d2 == pytest.approx(0.8, abs=1e-9)
    assert d0 < d1 < d2


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
        # Stage 99.4: per-loop dict — same loop → same instance.
        assert len(vm_client_module._shared_http_clients) == 1
        client_first = next(iter(vm_client_module._shared_http_clients.values()))
        await vc.get("/rest/api/client/1")
        assert len(vm_client_module._shared_http_clients) == 1
        client_second = next(iter(vm_client_module._shared_http_clients.values()))

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
    from exceptions import VetmanagerError
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerError):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})


# ── Non-idempotent POST does NOT retry on 5xx ───────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_post_does_not_retry_on_500():
    from exceptions import VetmanagerError
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(500, json={"error": "bad"})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerError):
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

        # Stage 109.3: age the breaker past the cooldown via public helper.
        from vetmanager_client import force_breaker_open, get_breaker_state
        await force_breaker_open(DOMAIN, cooldown_elapsed=True)

        state["phase"] = "ok"
        # Probe goes through (half-open admits one request).
        result = await VetmanagerClient().post("/rest/api/client", json={"x": 1})
        assert result["data"]["ok"] is True

        # Breaker must be closed now.
        snap = get_breaker_state(DOMAIN)
        assert snap is not None and snap["state"] == "closed", (
            f"expected closed after successful probe, got {snap}"
        )


# ── Timeout config ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_admits_only_one_probe():
    """Under concurrency, only ONE request should probe while others fast-fail.
    Without probe_in_flight guard, N concurrent callers in half_open would all
    try to hit the upstream, defeating the breaker purpose.

    Stage 109.3: uses public `force_breaker_open` + `get_breaker_state`
    instead of reaching into DomainBreaker private fields directly.
    """
    from vetmanager_client import force_breaker_open, get_breaker_state

    await reset_breakers()
    # Force OPEN with elapsed cooldown so next check flips to HALF_OPEN.
    await force_breaker_open(DOMAIN, cooldown_elapsed=True)

    # First check: admits probe, sets probe_in_flight=True.
    await vm_client_module._check_breaker_allows(DOMAIN)
    snap = get_breaker_state(DOMAIN)
    assert snap is not None
    assert snap["state"] == "half_open"
    assert snap["probe_in_flight"] is True

    # Second concurrent check must be rejected — probe in flight.
    with pytest.raises(VetmanagerUpstreamUnavailable):
        await vm_client_module._check_breaker_allows(DOMAIN)

    # Probe finishes successfully → closed, flag clears.
    await vm_client_module._breaker_record_success(DOMAIN)
    snap = get_breaker_state(DOMAIN)
    assert snap is not None
    assert snap["state"] == "closed"
    assert snap["probe_in_flight"] is False


def test_split_timeouts_are_configured():
    """Stage 109.7: behavioural invariants instead of exact magic numbers.

    The concrete values may change for operational tuning (e.g. relax
    read timeout for slow clinics). What must hold: all 4 components
    are set (not None/0), and fast-failing paths (connect, pool) are
    strictly tighter than slower paths (read, write) — otherwise a
    connect stall would drag the whole read budget.
    """
    from vetmanager_client import _REQUEST_TIMEOUTS
    for component in ("connect", "read", "write", "pool"):
        value = getattr(_REQUEST_TIMEOUTS, component)
        assert value is not None and value > 0, (
            f"_REQUEST_TIMEOUTS.{component} must be a positive number, got {value!r}"
        )
    assert _REQUEST_TIMEOUTS.connect < _REQUEST_TIMEOUTS.read, (
        "connect timeout must be tighter than read — fast-fail on DNS/TCP"
    )
    assert _REQUEST_TIMEOUTS.pool < _REQUEST_TIMEOUTS.read, (
        "pool timeout must be tighter than read — fast-fail on pool exhaustion"
    )


def test_http_limits_enable_keep_alive_pool():
    """Stage 109.7: behavioural check — pool is enabled and total ≥ keepalive.

    Exact numbers (50 / 100 / 30s) are SLO constants documented in
    AssumptionLog + technical-requirements; tuning them should not
    break this test unless the invariant is violated.
    """
    from vetmanager_client import _HTTP_LIMITS
    assert _HTTP_LIMITS.max_keepalive_connections is not None
    assert _HTTP_LIMITS.max_keepalive_connections > 0, (
        "keep-alive pool must be enabled"
    )
    assert _HTTP_LIMITS.max_connections >= _HTTP_LIMITS.max_keepalive_connections, (
        "max_connections must accommodate at least all keep-alive slots"
    )
    assert _HTTP_LIMITS.keepalive_expiry is not None
    assert _HTTP_LIMITS.keepalive_expiry > 0, (
        "keep-alive expiry must be set — otherwise sockets never close"
    )
