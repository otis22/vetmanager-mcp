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
import time
from urllib.parse import urljoin, urlparse
from weakref import WeakKeyDictionary

import httpx

from env_utils import env_float
from domain_validation import validate_domain
from exceptions import HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_validation import validate_resolved_vetmanager_origin
from observability_logging import RUNTIME_LOGGER
from request_context import get_current_request_context
from service_metrics import record_host_resolution, record_upstream_failure, record_upstream_request
from upstream_transport import classify_http_status, classify_transport_error


BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
BILLING_API_ALIAS = "https://billing-api.vetmanager.ru/host/{domain}"
# Two sources with one retry each fit comfortably inside the 30-second GET budget.
_REQUEST_TIMEOUT = httpx.Timeout(connect=1.5, read=2.0, write=2.0, pool=1.0)
_DEFAULT_MAX_RETRIES = 1
GUESSED_HOST_CACHE_TTL_SECONDS = 15.0
_LOOKUP_DEADLINE_SECONDS = 2.5
_PROBE_PATH = "/rest/api/user/1"

BILLING_RESOLVER_CACHE_TTL_SECONDS = env_float(
    "BILLING_RESOLVER_CACHE_TTL_SECONDS", 300.0
)


_resolved_host_cache: dict[str, tuple[str, float, str | None]] = {}

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
        # Match httpx's default trust roots and environment overrides.
        tls = httpx.create_ssl_context(verify=True, trust_env=True)
        # OpenSSL 3.5 otherwise offers a large post-quantum ClientHello. The
        # classic P-256 share works through the container network path.
        tls.set_ecdh_curve("prime256v1")
        client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUT, verify=tls)
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
    # Этап 285: ноль — законное значение, поэтому positive_only отключён.
    grace_seconds = env_float(
        "VM_HTTP_CLIENT_CLOSE_GRACE_SECONDS", 0.0, positive_only=False
    )
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
    domain = validate_domain(domain)
    # Stage 113.F7: cache fast-path. Hit skips HTTP + TLS entirely.
    cached = _resolved_host_cache.get(domain)
    if cached is not None:
        value, expires_at, guess_method = cached
        if time.monotonic() < expires_at:
            if guess_method:
                _observe_guessed_host(domain, value, guess_method, correlation_id)
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
            value, expires_at, guess_method = cached
            if time.monotonic() < expires_at:
                if guess_method:
                    _observe_guessed_host(domain, value, guess_method, correlation_id)
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

    resolved = await asyncio.shield(task)
    cached = _resolved_host_cache.get(domain)
    if cached is not None and cached[2]:
        _observe_guessed_host(domain, resolved, cached[2], correlation_id)
    return resolved


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


def _observe_guessed_host(
    domain: str, host: str, method: str, correlation_id: str | None
) -> None:
    record_upstream_request(target="billing_api", status=f"guessed_{method}", duration_seconds=0.0)
    RUNTIME_LOGGER.warning(
        "Using guessed Vetmanager host after both billing sources failed.",
        extra={"event_name": "billing_host_guessed", "domain": domain,
               "resolved_host": host, "selection_method": method,
               "correlation_id": correlation_id},
    )


async def _resolve_vetmanager_host_uncached(
    domain: str,
    *,
    max_retries: int,
    correlation_id: str | None = None,
) -> str:
    """Observe one shared uncached resolution, including retries."""
    started = time.monotonic()
    outcome = "success"
    try:
        return await _resolve_vetmanager_host_uncached_impl(
            domain, max_retries=max_retries, correlation_id=correlation_id)
    except asyncio.CancelledError:
        outcome = "cancelled"
        raise
    except BaseException:
        outcome = "error"
        raise
    finally:
        record_host_resolution(duration_seconds=time.monotonic() - started, outcome=outcome)


async def _resolve_vetmanager_host_uncached_impl(
    domain: str,
    *,
    max_retries: int,
    correlation_id: str | None = None,
) -> str:
    """Resolve host after cache/coalescing fast paths have been handled."""

    client = await _get_shared_client()
    correlation_id = correlation_id or get_current_request_context().get("correlation_id")
    transport_failures = 0
    last_error: Exception | None = None
    for source, template in (("cloud", BILLING_API), ("alias", BILLING_API_ALIAS)):
        url = template.format(domain=domain)
        for attempt in range(min(max_retries, 1) + 1):
            try:
                return await _lookup_billing_host(client, url, domain, source)
            except HostResolutionError as exc:
                # 5xx may be transient; an authoritative 4xx or invalid body
                # must never turn into a guessed clinic address.
                if getattr(exc, "billing_5xx", False) and source == "cloud":
                    last_error = exc
                    break
                raise
            except httpx.RequestError as exc:
                reason = classify_transport_error(exc)
                last_error = exc
                RUNTIME_LOGGER.warning(
                    "Billing API transport failure",
                    extra={"event_name": "billing_api_transport_failure", "domain": domain,
                           "target": "billing_api", "source": source, "reason": reason,
                           "attempt": attempt + 1, "correlation_id": correlation_id},
                )
                if attempt < min(max_retries, 1):
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                transport_failures += 1
                break

    if transport_failures == 2:
        guessed, method = await _probe_clinic_origin(client, domain)
        _resolved_host_cache[domain] = (
            guessed, time.monotonic() + GUESSED_HOST_CACHE_TTL_SECONDS, method
        )
        return guessed
    if isinstance(last_error, httpx.TimeoutException):
        raise VetmanagerTimeoutError(
            "Timeout resolving Vetmanager host. Please retry shortly."
        ) from last_error
    if isinstance(last_error, httpx.RequestError):
        raise VetmanagerError(
            "Network error resolving Vetmanager host. Please retry shortly."
        ) from last_error
    if last_error is not None:
        raise last_error
    raise VetmanagerError("Failed to resolve Vetmanager host.")


async def _lookup_billing_host(
    client: httpx.AsyncClient, url: str, domain: str, source: str
) -> str:
    """Make one authoritative billing lookup; preserve response validation."""
    started = time.monotonic()
    try:
        response = await _bounded_get(client, url)
    except httpx.RequestError as exc:
        elapsed = time.monotonic() - started
        reason = classify_transport_error(exc)
        record_upstream_failure(target="billing_api", reason=reason)
        record_upstream_request(target="billing_api", status=reason, duration_seconds=elapsed)
        raise
    elapsed = time.monotonic() - started
    if response.status_code >= 400:
        reason = classify_http_status(response.status_code)
        record_upstream_failure(target="billing_api", reason=reason)
        record_upstream_request(target="billing_api", status=reason, duration_seconds=elapsed)
        error = HostResolutionError(
            f"Billing API returned HTTP {response.status_code}. Please retry shortly."
        )
        error.billing_5xx = response.status_code >= 500
        raise error
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict) and data.get("success") is False:
        record_upstream_failure(target="billing_api", reason="malformed_response")
        record_upstream_request(target="billing_api", status="malformed_response", duration_seconds=elapsed)
        raise HostResolutionError("Unexpected billing API host response. Please retry shortly.")
    nested_data = data.get("data") if isinstance(data, dict) else None
    host = (
        nested_data.get("url") or data.get("url")
        if isinstance(nested_data, dict)
        else data.get("url") if isinstance(data, dict) else None
    )
    if not host:
        record_upstream_failure(target="billing_api", reason="malformed_response")
        record_upstream_request(target="billing_api", status="malformed_response", duration_seconds=elapsed)
        raise HostResolutionError("Unexpected billing API host response. Please retry shortly.")
    host = host.rstrip("/")
    if not host.startswith("http"):
        host = f"https://{host}"
    try:
        validated = validate_resolved_vetmanager_origin(host, domain=domain)
    except HostResolutionError as exc:
        record_upstream_failure(target="billing_api", reason="invalid_origin")
        record_upstream_request(target="billing_api", status="invalid_origin", duration_seconds=elapsed)
        raise HostResolutionError(
            "Billing API returned an invalid host response. Please retry shortly."
        ) from exc
    record_upstream_request(target="billing_api", status="http_200", duration_seconds=elapsed)
    RUNTIME_LOGGER.debug(
        "Resolved billing host.",
        extra={"event_name": "billing_host_resolved", "domain": domain,
               "source": source, "resolved_host": validated},
    )
    _resolved_host_cache[domain] = (
        validated, time.monotonic() + BILLING_RESOLVER_CACHE_TTL_SECONDS, None
    )
    return validated


async def _bounded_get(client: httpx.AsyncClient, url: str) -> httpx.Response:
    """Cap each network step even when several HTTP timeout phases occur."""
    try:
        return await asyncio.wait_for(
            client.get(url, follow_redirects=False), timeout=_LOOKUP_DEADLINE_SECONDS
        )
    except asyncio.TimeoutError as exc:
        raise httpx.ReadTimeout("Host lookup deadline exceeded") from exc


async def _probe_clinic_origin(
    client: httpx.AsyncClient, domain: str
) -> tuple[str, str]:
    """Verify a guessed clinic without credentials or following redirects."""
    vm2 = f"https://{domain}.vetmanager2.ru"
    ru = f"https://{domain}.vetmanager.ru"
    try:
        first = await _bounded_get(client, f"{vm2}{_PROBE_PATH}")
    except httpx.RequestError:
        first = None
    if first is not None and (first.status_code == 401 or 200 <= first.status_code < 300):
        return validate_resolved_vetmanager_origin(vm2, domain=domain), "vm2_direct"

    try:
        second = await _bounded_get(client, f"{ru}{_PROBE_PATH}")
    except httpx.RequestError as exc:
        raise HostResolutionError("Unable to verify Vetmanager clinic host.") from exc
    if second.status_code == 401 or 200 <= second.status_code < 300:
        return validate_resolved_vetmanager_origin(ru, domain=domain), "ru_direct"
    if second.status_code == 404:
        raise HostResolutionError("Vetmanager clinic domain not found.")
    if 300 <= second.status_code < 400:
        location = second.headers.get("location", "")
        if not location:
            raise HostResolutionError("Vetmanager clinic redirect is missing a location.")
        try:
            parsed = urlparse(urljoin(f"{ru}{_PROBE_PATH}", location))
            safe_port = parsed.port in (None, 443)
        except ValueError as exc:
            raise HostResolutionError("Vetmanager clinic redirect is unsafe.") from exc
        if parsed.scheme == "https" and parsed.hostname in {
            f"{domain}.vetmanager2.ru", f"{domain}.vetmanager.ru"
        } and not parsed.username and not parsed.password and safe_port and parsed.path != "/404":
            target = validate_resolved_vetmanager_origin(
                f"https://{parsed.hostname}", domain=domain
            )
            return target, "ru_redirect"
        raise HostResolutionError("Vetmanager clinic domain not found or redirect is unsafe.")
    raise HostResolutionError("Unable to verify Vetmanager clinic host.")
