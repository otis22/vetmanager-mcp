"""Stage 101 — tests hardening II.

Additional regressions not already covered by stage 94 + inline fixes in
stages 91/93/96:

- 101.5 HALF_OPEN failed probe re-OPEN with fresh cooldown.
- 101.7 Sanitizer allowlist coverage: unlisted api-* key IS redacted.
"""

from __future__ import annotations

import time

import pytest

import vetmanager_client as vm_client_module
from error_tracking import _sanitize_event
from vetmanager_client import (
    _BREAKER_COOLDOWN_SECONDS,
    _BREAKER_FAILURE_THRESHOLD,
    reset_breakers,
)

DOMAIN = "stage101-test"


# ── 101.5 HALF_OPEN failed probe → OPEN with fresh cooldown ─────────────────


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens_with_fresh_cooldown():
    """Stage 91 had only HALF_OPEN → CLOSED (success) test. This covers the
    HALF_OPEN → OPEN (failure) transition: when probe fails, breaker must
    flip back to OPEN with freshly-reset opened_at so subsequent callers
    wait the full cooldown again, not zero seconds."""
    await reset_breakers()
    breaker = await vm_client_module._get_breaker(DOMAIN)

    # Force into OPEN state, elapsed past cooldown so next check admits a probe.
    async with breaker.lock:
        breaker.state = "open"
        breaker.opened_at = time.monotonic() - _BREAKER_COOLDOWN_SECONDS - 1

    # Admit probe.
    await vm_client_module._check_breaker_allows(DOMAIN)
    assert breaker.state == "half_open"
    assert breaker.probe_in_flight is True

    t_before_failure = time.monotonic()

    # Probe failed.
    await vm_client_module._breaker_record_failure(DOMAIN)

    # Must transition back to OPEN with fresh cooldown.
    assert breaker.state == "open"
    assert breaker.probe_in_flight is False
    # opened_at should be approximately 'now' (after t_before_failure).
    assert breaker.opened_at >= t_before_failure - 0.01


# ── 101.7 Sanitizer redacts unlisted api-* key ──────────────────────────────


def test_sanitizer_redacts_unlisted_api_prefixed_key():
    """Stage 89 allowlist covers api-version / x-api-version / api_version.
    Any OTHER key containing 'api' substring MUST still be redacted — the
    allowlist is narrow-scoped to version-style metadata only."""
    event = {"request": {"headers": {
        "x-api-client-id": "secret-client-id",
        "x-api-secret": "hunter2",
        "x-custom-api-token": "t0k3n",
        # Safe allowlisted:
        "x-api-version": "2024-06",
    }}}
    _sanitize_event(event, None)
    hdrs = event["request"]["headers"]
    assert hdrs["x-api-client-id"] == "[Filtered]"
    assert hdrs["x-api-secret"] == "[Filtered]"
    assert hdrs["x-custom-api-token"] == "[Filtered]"
    # Allowlisted one preserved.
    assert hdrs["x-api-version"] == "2024-06"


def test_sanitizer_redacts_stacktrace_frame_vars():
    """Stage 100.1 regression — frame vars with credential-shaped names
    redacted even inside nested exception.values[].stacktrace.frames[].vars."""
    event = {
        "exception": {
            "values": [
                {
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "app.py",
                                "vars": {
                                    "bearer_token": "leaked",
                                    "user_count": 42,
                                },
                            }
                        ]
                    }
                }
            ]
        }
    }
    _sanitize_event(event, None)
    vars_out = event["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]
    assert vars_out["bearer_token"] == "[Filtered]"
    # Non-sensitive local preserved.
    assert vars_out["user_count"] == 42


def test_sanitizer_redacts_breadcrumb_data():
    event = {
        "breadcrumbs": {
            "values": [
                {"category": "http", "data": {"api_key": "x", "status": 200}},
                {"category": "log", "data": {"message": "ok", "password": "p"}},
            ]
        }
    }
    _sanitize_event(event, None)
    bc = event["breadcrumbs"]["values"]
    assert bc[0]["data"]["api_key"] == "[Filtered]"
    assert bc[0]["data"]["status"] == 200
    assert bc[1]["data"]["password"] == "[Filtered]"
    assert bc[1]["data"]["message"] == "ok"
