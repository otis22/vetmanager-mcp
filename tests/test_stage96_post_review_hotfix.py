"""Stage 96 — regression tests for post-super-review hot-fixes.

Covers:
- 96.1 update_admission payload field mapping (pet_id→patient_id, doctor_id→user_id,
  date→admission_date). Parallel to stage 86 test_create_admission.
- 96.2 get_client_profile next_admission uses IN-tuple of ACTIVE_ADMISSION_STATUSES,
  not phantom status='active'.
- 96.3 Partial-gather re-raises CancelledError instead of swallowing it as section.
- 96.4 Breaker HALF_OPEN probe that returns 4xx clears probe_in_flight + breaker.
- 96.5 filters.in_/not_in reject empty list with ValueError.
- 96.6 _parse_retry_after rejects inf/nan and clamps to sane max.
"""

from __future__ import annotations

import asyncio
import json
import math
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

import vetmanager_client as vm_client_module
from exceptions import AuthError, NotFoundError, VetmanagerUpstreamUnavailable
from filters import in_, not_in
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from tools.admission import ACTIVE_ADMISSION_STATUSES
from vetmanager_client import (
    _BREAKER_COOLDOWN_SECONDS,
    _RETRY_AFTER_MAX_SECONDS,
    _parse_retry_after,
    VetmanagerClient,
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


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


# ── 96.1 update_admission payload mapping ───────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_update_admission_maps_fields_to_api_contract():
    """Same boundary mapping as create_admission (stage 86): external
    pet_id/doctor_id/date → patient_id/user_id/admission_date in payload."""
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/admission/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_admission",
            {
                "admission_id": 42,
                "pet_id": 5,
                "doctor_id": 3,
                "date": "2026-05-01T10:00:00",
                "status": "accepted",
            },
        )
    body = _body_of(route)
    assert body["patient_id"] == 5
    assert body["user_id"] == 3
    assert body["admission_date"] == "2026-05-01T10:00:00"
    assert body["status"] == "accepted"
    assert "pet_id" not in body
    assert "doctor_id" not in body
    assert "date" not in body


@pytest.mark.asyncio
@respx.mock
async def test_update_admission_only_sends_provided_fields():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/admission/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_admission",
            {"admission_id": 42, "status": "not_confirmed"},
        )
    body = _body_of(route)
    assert body == {"status": "not_confirmed"}


# ── 96.2 get_client_profile status IN tuple ─────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_client_profile_next_admission_uses_status_in_tuple():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/7").mock(
        return_value=httpx.Response(200, json={"data": {"client": {"id": 7}}})
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"invoice": []}})
    )
    adm_route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"admission": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_client_profile", {"client_id": 7})

    # next_admission call is the last GET to /admission with limit=1.
    found_in_filter = False
    for call in adm_route.calls:
        url = str(call.request.url)
        q = parse_qs(urlparse(url).query)
        if q.get("limit", ["0"])[0] != "1":
            continue
        filter_list = json.loads(q["filter"][0])
        for f in filter_list:
            if f.get("property") == "status":
                assert f.get("operator") == "IN"
                assert set(f["value"]) == set(ACTIVE_ADMISSION_STATUSES)
                # Ensure the phantom 'active' value is NOT in there.
                assert "active" not in f["value"]
                found_in_filter = True
    assert found_in_filter, "next_admission call must use status IN tuple"


# ── 96.3 Partial-gather re-raises CancelledError ─────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_client_profile_reraises_cancelled_error(monkeypatch):
    """CancelledError is BaseException — partial-gather must not swallow it."""
    billing_mock()

    # Make /client raise CancelledError
    async def _cancel(request):
        raise asyncio.CancelledError()

    respx.get(f"{BASE}/rest/api/client/9").mock(side_effect=_cancel)
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"invoice": []}})
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"admission": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(asyncio.CancelledError):
            await mcp.call_tool("get_client_profile", {"client_id": 9})


# ── 96.4 Breaker 4xx on probe clears probe_in_flight ────────────────────────


@pytest.mark.asyncio
async def test_half_open_probe_404_clears_probe_in_flight():
    """4xx response during HALF_OPEN means upstream is alive — breaker must
    NOT stay wedged with probe_in_flight=True.

    Stage 109.3: uses public `force_breaker_open` + `get_breaker_state`.
    """
    from vetmanager_client import force_breaker_open, get_breaker_state

    await vm_client_module.reset_breakers()
    # Force OPEN with elapsed cooldown → next check admits probe.
    await force_breaker_open(DOMAIN, cooldown_elapsed=True)

    # Admit the probe — sets state=half_open, probe_in_flight=True.
    await vm_client_module._check_breaker_allows(DOMAIN)
    snap = get_breaker_state(DOMAIN)
    assert snap is not None
    assert snap["state"] == "half_open"
    assert snap["probe_in_flight"] is True

    # Simulate 4xx handling path in _request: calls _breaker_record_success.
    await vm_client_module._breaker_record_success(DOMAIN)

    # Breaker must now be closed and probe_in_flight cleared.
    snap = get_breaker_state(DOMAIN)
    assert snap is not None
    assert snap["state"] == "closed"
    assert snap["probe_in_flight"] is False


# ── 96.5 in_/not_in reject empty list ────────────────────────────────────────


def test_in_rejects_empty_list():
    with pytest.raises(ValueError, match="at least one value"):
        in_("id", [])


def test_in_rejects_empty_tuple():
    with pytest.raises(ValueError, match="at least one value"):
        in_("id", ())


def test_not_in_rejects_empty_list():
    with pytest.raises(ValueError, match="at least one value"):
        not_in("status", [])


# ── 96.6 _parse_retry_after rejects non-finite + clamps ──────────────────────


def test_parse_retry_after_rejects_inf():
    assert _parse_retry_after("inf") is None
    assert _parse_retry_after("Infinity") is None
    assert _parse_retry_after("-inf") is None


def test_parse_retry_after_rejects_nan():
    assert _parse_retry_after("nan") is None
    assert _parse_retry_after("NaN") is None


def test_parse_retry_after_clamps_large_values():
    """Retry-After: 1e9 → clamp to _RETRY_AFTER_MAX_SECONDS (5 minutes)."""
    parsed = _parse_retry_after("1000000000")
    assert parsed == _RETRY_AFTER_MAX_SECONDS
    assert parsed <= 300.0


def test_parse_retry_after_preserves_reasonable_values():
    assert _parse_retry_after("5") == 5.0
    assert _parse_retry_after("120") == 120.0
