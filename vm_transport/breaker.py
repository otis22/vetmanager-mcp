"""Per-domain circuit breaker for the Vetmanager upstream.

Stage 103d: extracted from `vetmanager_client.py`.

State transitions:
    CLOSED → (N failures in window) → OPEN → (cooldown) → HALF_OPEN → (success) → CLOSED
                                                                        ↓ (fail)
                                                                      → OPEN (new cooldown)

`probe_in_flight` enforces strict single-probe semantics in HALF_OPEN:
under concurrency, only one request is admitted to test the upstream;
the rest fast-fail until the probe completes (success → CLOSED and other
callers proceed normally; failure → OPEN with fresh cooldown).

Env-tunable thresholds (stage 99.5):
- BREAKER_FAILURE_THRESHOLD (default 5)
- BREAKER_WINDOW_SECONDS    (default 60.0)
- BREAKER_COOLDOWN_SECONDS  (default 30.0)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from env_utils import env_float, env_int
from exceptions import VetmanagerUpstreamUnavailable
from observability_logging import RUNTIME_LOGGER
from service_metrics import record_upstream_failure, record_upstream_request

# Module-level constants — evaluated at import. These are kept for existing
# tests that reference them as **default values** (e.g. `range(BREAKER_FAILURE_THRESHOLD)`
# loop count). Stage 113.1: runtime no longer reads these directly —
# `breaker_record_failure` / `check_breaker_allows` go through the
# accessor functions below so `monkeypatch.setenv` takes effect.
#
# WARNING: patching these module attributes (e.g. `monkeypatch.setattr(...,
# "BREAKER_FAILURE_THRESHOLD", 2)`) does NOT change runtime behavior any more.
# Use `monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", "2")` instead. Listed as
# a migration follow-up in stage 113 AssumptionLog.
BREAKER_FAILURE_THRESHOLD = env_int("BREAKER_FAILURE_THRESHOLD", 5)
BREAKER_WINDOW_SECONDS = env_float("BREAKER_WINDOW_SECONDS", 60.0)
BREAKER_COOLDOWN_SECONDS = env_float("BREAKER_COOLDOWN_SECONDS", 30.0)


def breaker_failure_threshold() -> int:
    """Current breaker failure threshold from env (per-call read).

    Stage 113.1 (super-review 2026-04-19, codex-blindspot H10): the
    module-level constants above are evaluated at import time, so tests
    using `monkeypatch.setenv("BREAKER_FAILURE_THRESHOLD", ...)` after
    import have no effect. Callers inside this module read through this
    accessor instead so env overrides take effect immediately.
    """
    return env_int("BREAKER_FAILURE_THRESHOLD", 5)


def breaker_window_seconds() -> float:
    """Current breaker sliding-window size from env (per-call read)."""
    return env_float("BREAKER_WINDOW_SECONDS", 60.0)


def breaker_cooldown_seconds() -> float:
    """Current breaker OPEN→HALF_OPEN cooldown from env (per-call read)."""
    return env_float("BREAKER_COOLDOWN_SECONDS", 30.0)


@dataclass
class DomainBreaker:
    """Per-domain circuit breaker state."""

    state: str = "closed"  # closed | open | half_open
    consecutive_failures: int = 0
    window_start: float = 0.0
    opened_at: float = 0.0
    probe_in_flight: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


# Registry is shared; `tests/conftest.py` clears it between tests.
_breakers: dict[str, DomainBreaker] = {}
_breakers_global_lock = asyncio.Lock()


async def get_breaker(domain: str) -> DomainBreaker:
    breaker = _breakers.get(domain)
    if breaker is not None:
        return breaker
    async with _breakers_global_lock:
        breaker = _breakers.get(domain)
        if breaker is None:
            breaker = DomainBreaker()
            _breakers[domain] = breaker
        return breaker


async def reset_breakers() -> None:
    """Clear all breaker state. For tests."""
    async with _breakers_global_lock:
        _breakers.clear()


async def check_breaker_allows(domain: str) -> None:
    """Raise VetmanagerUpstreamUnavailable if breaker is OPEN and cooldown
    has not elapsed, OR if already HALF_OPEN with a probe in flight (strict
    single-probe semantics under concurrency). Transitions OPEN → HALF_OPEN
    and marks probe_in_flight when admitting the first probe after cooldown.

    Stage 98.2: circuit_open / circuit_half_open_busy fast-fails are
    recorded in `record_upstream_request` (status="circuit_open") so a
    single query on `vetmanager_upstream_requests_total` sees the full
    error rate including breaker fast-fails.
    """
    breaker = await get_breaker(domain)
    async with breaker.lock:
        if breaker.state == "open":
            elapsed = time.monotonic() - breaker.opened_at
            cooldown = breaker_cooldown_seconds()
            if elapsed < cooldown:
                record_upstream_failure(
                    target="vetmanager_api", reason="circuit_open"
                )
                record_upstream_request(
                    target="vetmanager_api",
                    status="circuit_open",
                    duration_seconds=0.0,
                )
                raise VetmanagerUpstreamUnavailable(
                    f"VM API circuit breaker open for {domain}; "
                    f"retry after {cooldown - elapsed:.0f}s",
                    retry_after_seconds=cooldown - elapsed,
                )
            # Cooldown elapsed — transition to HALF_OPEN and admit one probe.
            breaker.state = "half_open"
            breaker.probe_in_flight = True
            return
        if breaker.state == "half_open":
            if breaker.probe_in_flight:
                record_upstream_failure(
                    target="vetmanager_api", reason="circuit_half_open_busy"
                )
                record_upstream_request(
                    target="vetmanager_api",
                    status="circuit_half_open_busy",
                    duration_seconds=0.0,
                )
                raise VetmanagerUpstreamUnavailable(
                    f"VM API circuit breaker half-open for {domain}; "
                    "probe already in flight",
                    retry_after_seconds=1.0,
                )
            # First caller after a previous probe cleared — admit as new probe.
            breaker.probe_in_flight = True


async def breaker_record_success(domain: str) -> None:
    breaker = await get_breaker(domain)
    async with breaker.lock:
        previous_state = breaker.state
        breaker.consecutive_failures = 0
        breaker.window_start = 0.0
        breaker.probe_in_flight = False
        if breaker.state in ("half_open", "open"):
            breaker.state = "closed"
            # Stage 107.9 (obs): log recovery transition so incidents have
            # a clear "circuit closed at T" marker in logs; dashboards
            # also see the transition via upstream_requests counter.
            RUNTIME_LOGGER.info(
                "Circuit breaker recovered",
                extra={
                    "event_name": "circuit_breaker_closed",
                    "domain": domain,
                    "previous_state": previous_state,
                },
            )


async def breaker_record_failure(domain: str) -> None:
    breaker = await get_breaker(domain)
    async with breaker.lock:
        now = time.monotonic()
        previous_state = breaker.state
        if previous_state == "half_open":
            # Probe failed — back to OPEN with fresh cooldown.
            breaker.state = "open"
            breaker.opened_at = now
            breaker.probe_in_flight = False
            # Stage 112.1 (super-review 2026-04-19): symmetric log for probe-fail
            # transition; pairs with recovery log on success path.
            RUNTIME_LOGGER.warning(
                "Circuit breaker re-opened after failed probe",
                extra={
                    "event_name": "circuit_breaker_opened",
                    "domain": domain,
                    "cause": "probe_failed",
                },
            )
            return
        # Stage 113.1: read env via accessor so test overrides take effect.
        window = breaker_window_seconds()
        threshold = breaker_failure_threshold()
        # Increment within sliding window (covers CLOSED and OPEN sustained-failure paths).
        if breaker.window_start == 0.0 or (now - breaker.window_start) > window:
            breaker.window_start = now
            breaker.consecutive_failures = 1
        else:
            breaker.consecutive_failures += 1
        if breaker.consecutive_failures >= threshold:
            breaker.state = "open"
            breaker.opened_at = now
            # Stage 112.1: log ONLY on actual CLOSED→OPEN transition (not
            # on every sustained failure while already OPEN). Codex review
            # flagged duplicate emission under concurrent in-flight failures.
            if previous_state != "open":
                RUNTIME_LOGGER.warning(
                    "Circuit breaker opened",
                    extra={
                        "event_name": "circuit_breaker_opened",
                        "domain": domain,
                        "consecutive_failures": breaker.consecutive_failures,
                        "threshold": threshold,
                        "cause": "threshold_reached",
                    },
                )


def get_breaker_state(domain: str) -> dict | None:
    """Return public snapshot of one domain's breaker state, or None if
    the domain has no breaker yet. For tests."""
    breaker = _breakers.get(domain)
    if breaker is None:
        return None
    return {
        "state": breaker.state,
        "consecutive_failures": breaker.consecutive_failures,
        "probe_in_flight": breaker.probe_in_flight,
        "opened_at": breaker.opened_at,
        "window_start": breaker.window_start,
    }


async def force_breaker_open(domain: str, *, cooldown_elapsed: bool = False) -> None:
    """Test helper: push a breaker into OPEN state without driving real
    failures through `_request`. If cooldown_elapsed=True, also backdates
    opened_at so the next check transitions to HALF_OPEN."""
    breaker = await get_breaker(domain)
    async with breaker.lock:
        breaker.state = "open"
        now = time.monotonic()
        breaker.opened_at = (
            now - breaker_cooldown_seconds() - 1 if cooldown_elapsed else now
        )
        breaker.probe_in_flight = False
