"""Stage 112: observability integrity — breaker transitions, integration failures,
url path scrubbing, correlation_id hygiene, retry log level."""

from __future__ import annotations

import logging

import pytest

from vm_transport.breaker import (
    BREAKER_FAILURE_THRESHOLD,
    breaker_record_failure,
    breaker_record_success,
    force_breaker_open,
    reset_breakers,
)


# ── 112.1: breaker opened log ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_breaker_opens_emits_structured_warning_at_threshold(caplog):
    """CLOSED → OPEN transition logs circuit_breaker_opened exactly once."""
    await reset_breakers()
    caplog.set_level(logging.WARNING, logger="vetmanager.runtime")

    domain = "test-threshold.example.com"
    # N-1 failures must not trip the log (breaker still CLOSED).
    for _ in range(BREAKER_FAILURE_THRESHOLD - 1):
        await breaker_record_failure(domain)

    opened_before = [
        r for r in caplog.records
        if getattr(r, "event_name", None) == "circuit_breaker_opened"
    ]
    assert not opened_before, (
        "breaker_opened fired before threshold reached"
    )

    # N-th failure triggers CLOSED → OPEN.
    await breaker_record_failure(domain)

    opened = [
        r for r in caplog.records
        if getattr(r, "event_name", None) == "circuit_breaker_opened"
    ]
    assert len(opened) == 1, (
        f"expected exactly one circuit_breaker_opened log, got {len(opened)}"
    )
    rec = opened[0]
    assert rec.domain == domain
    assert rec.consecutive_failures == BREAKER_FAILURE_THRESHOLD
    assert rec.threshold == BREAKER_FAILURE_THRESHOLD
    assert rec.cause == "threshold_reached"
    await reset_breakers()


@pytest.mark.asyncio
async def test_breaker_halfopen_probe_fail_reopens_with_log(caplog):
    """HALF_OPEN → OPEN (probe failed) logs circuit_breaker_opened."""
    await reset_breakers()
    caplog.set_level(logging.WARNING, logger="vetmanager.runtime")

    domain = "test-halfopen.example.com"
    await force_breaker_open(domain, cooldown_elapsed=True)
    # Manually flip to HALF_OPEN with probe_in_flight — simulate what
    # check_breaker_allows does on first call after cooldown.
    from vm_transport.breaker import get_breaker
    breaker = await get_breaker(domain)
    async with breaker.lock:
        breaker.state = "half_open"
        breaker.probe_in_flight = True
    caplog.clear()

    await breaker_record_failure(domain)

    opened = [
        r for r in caplog.records
        if getattr(r, "event_name", None) == "circuit_breaker_opened"
    ]
    assert len(opened) == 1
    rec = opened[0]
    assert rec.domain == domain
    assert rec.cause == "probe_failed"
    await reset_breakers()


@pytest.mark.asyncio
async def test_breaker_recovery_emits_closed_log(caplog):
    """Recovery (OPEN → CLOSED via success) already logs circuit_breaker_closed (stage 107.9)."""
    await reset_breakers()
    caplog.set_level(logging.INFO, logger="vetmanager.runtime")

    domain = "test-recovery.example.com"
    await force_breaker_open(domain, cooldown_elapsed=True)
    from vm_transport.breaker import get_breaker
    breaker = await get_breaker(domain)
    async with breaker.lock:
        breaker.state = "half_open"
        breaker.probe_in_flight = True
    caplog.clear()

    await breaker_record_success(domain)

    closed = [
        r for r in caplog.records
        if getattr(r, "event_name", None) == "circuit_breaker_closed"
    ]
    assert len(closed) == 1
    assert closed[0].previous_state == "half_open"
    await reset_breakers()
