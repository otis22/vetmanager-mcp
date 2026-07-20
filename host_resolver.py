"""Billing API host resolution for Vetmanager domains.

Resolves a clinic subdomain (e.g. "myclinic") to a validated HTTPS origin
(e.g. "https://myclinic.vetmanager.cloud") by querying the Vetmanager
billing API.

Stage 113.F7 (super-review 2026-04-19): resilience hardening.

- **Shared `httpx.AsyncClient`**: one instance per-loop (not per-call) so
  TLS handshakes amortize over repeated lookups.
- **TTL cache** on successful resolutions (default 300s) keyed by domain.
  Failures are NOT cached so transient 5xx don't poison the cache.
- **Graceful shutdown** via `reset_billing_resolver()` integrates with
  `server._graceful_shutdown`.

Non-scope (deferred to stage 113b/c):
- Dedicated circuit breaker for billing-api (independent of per-clinic
  breakers in `vm_transport.breaker`). Requires extending breaker module
  for arbitrary upstream targets.
- Exponential backoff with jitter. Current linear retry preserved.
"""

from __future__ import annotations

import asyncio
import os
import time
from weakref import WeakKeyDictionary

import httpx

from env_utils import env_float
from exceptions import HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_validation import validate_resolved_vetmanager_origin
from observability_logging import RUNTIME_LOGGER
from request_context import get_current_request_context
from service_metrics import record_upstream_failure, record_upstream_request
from upstream_transport import classify_http_status, classify_transport_error


BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
# Stage 113.F7: tighter timeouts on billing-api — simple JSON lookup should
# complete sub-second. 10s read is generous; 3s connect catches DNS hangs.
_REQUEST_TIMEOUT = httpx.Timeout(connect=3.0, read=10.0, write=5.0, pool=2.0)
_DEFAULT_MAX_RETRIES = 1

BILLING_RESOLVER_CACHE_TTL_SECONDS = env_float(
    "BILLING_RESOLVER_CACHE_TTL_SECONDS", 300.0
)


_resolved_host_cache: dict[str, tuple[str, float]] = {}

# Stage 113.F7 (Codex arbitration follow-up): per-loop shared client to
# avoid "attached to different event loop" errors when callers run under
# `asyncio.run()` (tests, notebook reloads, future scripts). Mirrors the
# per-loop pattern in `vm_transport/pool.py`. Each loop gets its own
# AsyncClient + lock, resolving the residual correctness risk that would
# otherwise require full 113c-scope refactor.
_shared_clients_by_loop: WeakKeyDictionary[asyncio.AbstractEventLoop, httpx.AsyncClient] = (
    WeakKeyDictionary()
)
_shared_clients_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    WeakKeyDictionary()
)
_inflight_resolutions_by_loop: WeakKeyDictionary[
    asyncio.AbstractEventLoop, dict[str, asyncio.Task[str]]
] = WeakKeyDictionary()
_inflight_resolutions_locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = (
    WeakKeyDictionary()
)


def _current_loop_key() -> asyncio.AbstractEventLoop | None:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


async def _get_shared_client() -> httpx.AsyncClient:
    """Lazy-init a per-loop `httpx.AsyncClient` with tight timeouts.

    Shared across all `resolve_vetmanager_host` calls within one event
    loop so TLS handshakes amortize. Per-loop keying avoids
    cross-loop transport reuse that bites under `asyncio.run()` re-entry.
    """
    key = _current_loop_key()
    if key is None:
        raise RuntimeError("_get_shared_client() requires a running event loop")
    client = _shared_clients_by_loop.get(key)
    if client is not None and not client.is_closed:
        return client
    lock = _shared_clients_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _shared_clients_locks[key] = lock
    async with lock:
        client = _shared_clients_by_loop.get(key)
        if client is not None and not client.is_closed:
            return client
        client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT)
        _shared_clients_by_loop[key] = client
        return client


async def reset_billing_resolver() -> None:
    """Close all per-loop billing clients and clear the resolver cache.

    Called from tests (per-test isolation) and `server._graceful_shutdown`.
    Safe to call repeatedly.
    """
    _resolved_host_cache.clear()
    _inflight_resolutions_by_loop.clear()
    _inflight_resolutions_locks.clear()
    clients = list(_shared_clients_by_loop.values())
    _shared_clients_by_loop.clear()
    _shared_clients_locks.clear()
    for client in clients:
        try:
            await client.aclose()
        except Exception:
            pass
    grace_seconds = float(os.environ.get("VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", "0"))
    if grace_seconds > 0:
        # Let asyncio SSL/socket transports finish close callbacks before pytest's
        # unraisable-warning collector runs under `-W error`.
        await asyncio.sleep(grace_seconds)


async def resolve_vetmanager_host(
    domain: str,
    *,
    max_retries: int = _DEFAULT_MAX_RETRIES,
    correlation_id: str | None = None,
) -> str:
    """Resolve clinic domain to validated HTTPS origin via billing API.

    Args:
        domain: Clinic subdomain (already validated).
        max_retries: Number of retry attempts on transient errors. 0 = no retry.

    Returns:
        Validated HTTPS origin string, e.g. ``"https://myclinic.vetmanager.cloud"``.

    Raises:
        HostResolutionError: Billing API returned unexpected response or HTTP error.
        VetmanagerTimeoutError: All attempts timed out.
        VetmanagerError: Network error after all retries.
    """
    # Stage 113.F7: cache fast-path. Hit skips HTTP + TLS entirely.
    cached = _resolved_host_cache.get(domain)
    if cached is not None:
        value, expires_at = cached
        if time.monotonic() < expires_at:
            return value

    loop = _current_loop_key()
    if loop is None:
        raise RuntimeError("resolve_vetmanager_host() requires a running event loop")
    lock = _inflight_resolutions_locks.get(loop)
    if lock is None:
        lock = asyncio.Lock()
        _inflight_resolutions_locks[loop] = lock
    async with lock:
        cached = _resolved_host_cache.get(domain)
        if cached is not None:
            value, expires_at = cached
            if time.monotonic() < expires_at:
                return value
        inflight = _inflight_resolutions_by_loop.get(loop)
        if inflight is None:
            inflight = {}
            _inflight_resolutions_by_loop[loop] = inflight
        task = inflight.get(domain)
        if task is None:
            task = asyncio.create_task(
                _resolve_vetmanager_host_uncached(
                    domain, max_retries=max_retries, correlation_id=correlation_id
                )
            )
            inflight[domain] = task
            task.add_done_callback(
                lambda completed, loop=loop, domain=domain: _clear_inflight_resolution(
                    loop, domain, completed
                )
            )

    return await asyncio.shield(task)


def _clear_inflight_resolution(
    loop: asyncio.AbstractEventLoop,
    domain: str,
    completed: asyncio.Task[str],
) -> None:
    try:
        completed.exception()
    except asyncio.CancelledError:
        pass
    inflight = _inflight_resolutions_by_loop.get(loop)
    if inflight is not None and inflight.get(domain) is completed:
        inflight.pop(domain, None)


async def _resolve_vetmanager_host_uncached(
    domain: str,
    *,
    max_retries: int,
    correlation_id: str | None = None,
) -> str:
    """Resolve host after cache/coalescing fast paths have been handled."""

    url = BILLING_API.format(domain=domain)
    client = await _get_shared_client()
    correlation_id = correlation_id or get_current_request_context().get("correlation_id")

    for attempt in range(max_retries + 1):
        started = time.monotonic()
        try:
            response = await client.get(url)
            elapsed = time.monotonic() - started
            if response.status_code >= 400:
                reason = classify_http_status(response.status_code)
                record_upstream_failure(target="billing_api", reason=reason)
                record_upstream_request(
                    target="billing_api", status=reason, duration_seconds=elapsed,
                )
                raise HostResolutionError(
                    f"Billing API returned HTTP {response.status_code}. Please retry shortly."
                )
            try:
                data = response.json()
            except ValueError:
                data = None
            nested_data = data.get("data") if isinstance(data, dict) else None
            host = (
                nested_data.get("url") or data.get("url")
                if isinstance(nested_data, dict)
                else data.get("url") if isinstance(data, dict) else None
            )
            if not host:
                record_upstream_failure(target="billing_api", reason="malformed_response")
                record_upstream_request(
                    target="billing_api", status="malformed_response", duration_seconds=elapsed,
                )
                raise HostResolutionError(
                    "Unexpected billing API host response. Please retry shortly."
                )
            host = host.rstrip("/")
            if not host.startswith("http"):
                host = f"https://{host}"
            try:
                validated = validate_resolved_vetmanager_origin(host, domain=domain)
            except HostResolutionError as exc:
                record_upstream_failure(target="billing_api", reason="invalid_origin")
                record_upstream_request(
                    target="billing_api", status="invalid_origin", duration_seconds=elapsed,
                )
                raise HostResolutionError(
                    "Billing API returned an invalid host response. Please retry shortly."
                ) from exc
            record_upstream_request(
                target="billing_api", status="http_200", duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.debug(
                "Resolved billing host.",
                extra={
                    "event_name": "billing_host_resolved",
                    "domain": domain,
                    "resolved_host": validated,
                },
            )
            # Stage 113.F7: cache on success only. Failures NOT cached so
            # transient 5xx on billing-api don't poison lookups.
            _resolved_host_cache[domain] = (
                validated,
                time.monotonic() + BILLING_RESOLVER_CACHE_TTL_SECONDS,
            )
            return validated
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            if attempt < max_retries:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            reason = classify_transport_error(exc)
            record_upstream_failure(target="billing_api", reason=reason)
            record_upstream_request(
                target="billing_api", status=reason, duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Billing API transport failure",
                extra={"event_name": "billing_api_transport_failure", "domain": domain,
                       "target": "billing_api", "reason": reason, "attempt": attempt + 1,
                       "correlation_id": correlation_id},
            )
            raise VetmanagerTimeoutError(
                "Timeout resolving Vetmanager host. Please retry shortly."
            ) from exc
        except httpx.RequestError as exc:
            elapsed = time.monotonic() - started
            if attempt < max_retries:
                await asyncio.sleep(0.1 * (attempt + 1))
                continue
            reason = classify_transport_error(exc)
            record_upstream_failure(target="billing_api", reason=reason)
            record_upstream_request(
                target="billing_api", status=reason, duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Billing API transport failure",
                extra={"event_name": "billing_api_transport_failure", "domain": domain,
                       "target": "billing_api", "reason": reason, "attempt": attempt + 1,
                       "correlation_id": correlation_id},
            )
            raise VetmanagerError(
                "Network error resolving Vetmanager host. Please retry shortly."
            ) from exc

    raise VetmanagerError(f"Failed to resolve host for domain '{domain}' after {max_retries + 1} attempts.")
