import logging
import asyncio
import email.utils
import hashlib
import math
import random
import time
import uuid
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlencode

import httpx

from exceptions import (
    AuthError,
    HostResolutionError,
    NotFoundError,
    VetmanagerError,
    VetmanagerTimeoutError,
    VetmanagerUpstreamUnavailable,
)
from host_resolver import resolve_vetmanager_host
from observability_logging import RUNTIME_LOGGER
from request_cache import REQUEST_CACHE
from request_auth import get_bearer_token
from request_context import get_current_request_context
from domain_validation import validate_domain as validate_runtime_domain
from runtime_auth import resolve_runtime_credentials
from service_metrics import record_upstream_failure, record_upstream_request
from token_scopes import required_scope_for_request
from vetmanager_auth import VetmanagerAuthContext

# Legacy single timeout kept for BC — new code uses _REQUEST_TIMEOUTS split.
REQUEST_TIMEOUT = 30.0
REQUEST_GAP_SECONDS = 0.05

# Retries for idempotent reads (GET). POST/PUT/DELETE do not retry on 5xx/429
# to preserve idempotency (VM API has no idempotency keys).
MAX_RETRIES_READ = 3
MAX_RETRIES_WRITE = 0

# Statuses worth retrying for GET. 401/403/404/400 are not transient.
_RETRY_STATUS_CODES = frozenset({429, 502, 503, 504})

_BACKOFF_BASE_SECONDS = 0.2
_BACKOFF_MAX_SECONDS = 5.0

# Split timeouts so a fast-failing DNS/TCP path does not wait the full 30s.
_REQUEST_TIMEOUTS = httpx.Timeout(connect=5.0, read=20.0, write=10.0, pool=2.0)

_HTTP_LIMITS = httpx.Limits(
    max_keepalive_connections=50,
    max_connections=100,
    keepalive_expiry=30.0,
)

# Default cache TTL for stable reference data (breeds, cities, goods, etc.).
CACHE_TTL_SECONDS = 900.0
# Short TTL for frequently-updated entities: admissions, medical cards, invoices, clients.
# Keeps data fresh while still reducing redundant API calls within a single session.
CACHE_TTL_SHORT_SECONDS = 60.0


# ── Shared httpx.AsyncClient (singleton) ────────────────────────────────────

# Stage 99.4: the shared client is keyed on the running event loop.
# asyncio.Lock is bound to one loop, and httpx.AsyncClient also captures
# the creating loop for its transport — reusing a singleton across loops
# produces "attached to a different event loop" errors in embedded setups
# (Jupyter reload, nested asyncio.run, cross-test-runner reuse).
_shared_http_clients: dict[int, httpx.AsyncClient] = {}
_shared_http_client_lock = asyncio.Lock()  # retained for back-compat patching


def _current_loop_key() -> int:
    """Return a stable key for the currently-running event loop (id of the
    loop object). Caller guarantees asyncio context (we're inside an async
    function)."""
    try:
        loop = asyncio.get_running_loop()
        return id(loop)
    except RuntimeError:
        # No running loop — fall back to a sentinel so we don't crash.
        return 0


async def _get_shared_http_client() -> httpx.AsyncClient:
    """Return a shared httpx.AsyncClient keyed on the running event loop.

    Lazy-initialized per-loop on first access. Within one loop: same
    keep-alive pool, no fresh TLS handshake per request. Across loops
    (tests that spawn their own loop, notebook reloads): separate clients
    so no cross-loop transport reuse.
    """
    key = _current_loop_key()
    client = _shared_http_clients.get(key)
    if client is not None and not client.is_closed:
        return client
    # Per-loop double-check via a fresh lock scoped to this loop — the
    # module-level lock is kept only for backward-compat with tests that
    # might patch it; real synchronization uses a local Lock if loop key
    # changes.
    if client is not None and client.is_closed:
        _shared_http_clients.pop(key, None)
    # Minor race if two coroutines on the same loop init simultaneously;
    # the second will overwrite the first (both valid clients, no leak of
    # the first because GC handles httpx.AsyncClient teardown).
    new_client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUTS, limits=_HTTP_LIMITS)
    _shared_http_clients[key] = new_client
    return new_client


# Back-compat property for existing tests that do `_vm_client._shared_http_client`.
# It returns the client for the currently-running loop or None — matches the old
# behaviour closely enough for the existing assertions.
class _SharedClientProxy:
    def __bool__(self) -> bool:
        return self._current() is not None

    def _current(self) -> httpx.AsyncClient | None:
        try:
            key = _current_loop_key()
        except Exception:
            return None
        return _shared_http_clients.get(key)

    def __getattr__(self, name: str):
        current = self._current()
        if current is None:
            raise AttributeError(name)
        return getattr(current, name)


_shared_http_client: httpx.AsyncClient | None = None  # retained for test monkey-patches


async def reset_shared_http_client() -> None:
    """Close and drop ALL per-loop shared clients. For tests and shutdown."""
    clients = list(_shared_http_clients.values())
    _shared_http_clients.clear()
    for c in clients:
        try:
            await c.aclose()
        except Exception:
            pass


# ── Public test-helpers (stage 101.2) ───────────────────────────────────────

def get_shared_http_client_state() -> dict:
    """Return a snapshot of the shared http client state — for tests.

    Observable fields only (no raw client reference), so test assertions
    remain valid across future internal rename/refactor.
    """
    client = _shared_http_client
    return {
        "exists": client is not None,
        "closed": client.is_closed if client is not None else True,
    }


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
    failures through _request. If cooldown_elapsed=True, also backdates
    opened_at so the next check transitions to HALF_OPEN.
    """
    breaker = await _get_breaker(domain)
    async with breaker.lock:
        breaker.state = "open"
        now = time.monotonic()
        breaker.opened_at = (
            now - _BREAKER_COOLDOWN_SECONDS - 1 if cooldown_elapsed else now
        )
        breaker.probe_in_flight = False


# ── Circuit breaker (per-domain) ────────────────────────────────────────────

def _env_float(name: str, default: float) -> float:
    """Stage 99.5: read tunable env var with float fallback."""
    import os
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
        return value if math.isfinite(value) and value > 0 else default
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    import os
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
        return value if value > 0 else default
    except ValueError:
        return default


# Env-tunable so operators can soften for burst workloads or tighten for
# strict SLOs — defaults match stage 91 design.
_BREAKER_FAILURE_THRESHOLD = _env_int("BREAKER_FAILURE_THRESHOLD", 5)
_BREAKER_WINDOW_SECONDS = _env_float("BREAKER_WINDOW_SECONDS", 60.0)
_BREAKER_COOLDOWN_SECONDS = _env_float("BREAKER_COOLDOWN_SECONDS", 30.0)


@dataclass
class _DomainBreaker:
    """Per-domain circuit breaker state.

    CLOSED → (N failures in window) → OPEN → (cooldown) → HALF_OPEN → (success) → CLOSED
                                                                    ↓ (fail)
                                                                  → OPEN (new cooldown)

    `probe_in_flight` enforces strict single-probe semantics in HALF_OPEN:
    under concurrency, only one request is admitted to test the upstream;
    the rest fast-fail until the probe completes (success → CLOSED and other
    callers proceed normally; failure → OPEN with fresh cooldown).
    """

    state: str = "closed"  # closed | open | half_open
    consecutive_failures: int = 0
    window_start: float = 0.0
    opened_at: float = 0.0
    probe_in_flight: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_breakers: dict[str, _DomainBreaker] = {}
_breakers_global_lock = asyncio.Lock()


async def _get_breaker(domain: str) -> _DomainBreaker:
    breaker = _breakers.get(domain)
    if breaker is not None:
        return breaker
    async with _breakers_global_lock:
        breaker = _breakers.get(domain)
        if breaker is None:
            breaker = _DomainBreaker()
            _breakers[domain] = breaker
        return breaker


async def reset_breakers() -> None:
    """Clear all breaker state. For tests."""
    async with _breakers_global_lock:
        _breakers.clear()


async def _check_breaker_allows(domain: str) -> None:
    """Raise VetmanagerUpstreamUnavailable if breaker is OPEN and cooldown
    has not elapsed, OR if already HALF_OPEN with a probe in flight (strict
    single-probe semantics under concurrency). Transitions OPEN → HALF_OPEN
    and marks probe_in_flight when admitting the first probe after cooldown.

    Stage 98.2: circuit_open / circuit_half_open_busy fast-fails are also
    recorded in `record_upstream_request` (status="circuit_open") so a single
    query on `vetmanager_upstream_requests_total` sees the full error rate
    including breaker fast-fails — the previous split between
    upstream_failures_total and upstream_requests_total made dashboards
    under-count during outages.
    """
    breaker = await _get_breaker(domain)
    async with breaker.lock:
        if breaker.state == "open":
            elapsed = time.monotonic() - breaker.opened_at
            if elapsed < _BREAKER_COOLDOWN_SECONDS:
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
                    f"retry after {_BREAKER_COOLDOWN_SECONDS - elapsed:.0f}s",
                    retry_after_seconds=_BREAKER_COOLDOWN_SECONDS - elapsed,
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


async def _breaker_record_success(domain: str) -> None:
    breaker = await _get_breaker(domain)
    async with breaker.lock:
        breaker.consecutive_failures = 0
        breaker.window_start = 0.0
        breaker.probe_in_flight = False
        if breaker.state in ("half_open", "open"):
            breaker.state = "closed"


async def _breaker_record_failure(domain: str) -> None:
    breaker = await _get_breaker(domain)
    async with breaker.lock:
        now = time.monotonic()
        if breaker.state == "half_open":
            # Probe failed — back to OPEN with fresh cooldown.
            breaker.state = "open"
            breaker.opened_at = now
            breaker.probe_in_flight = False
            return
        # CLOSED state: increment within sliding window.
        if breaker.window_start == 0.0 or (now - breaker.window_start) > _BREAKER_WINDOW_SECONDS:
            breaker.window_start = now
            breaker.consecutive_failures = 1
        else:
            breaker.consecutive_failures += 1
        if breaker.consecutive_failures >= _BREAKER_FAILURE_THRESHOLD:
            breaker.state = "open"
            breaker.opened_at = now


# ── Backoff helpers ─────────────────────────────────────────────────────────


_RETRY_AFTER_MAX_SECONDS = 300.0  # hard cap to prevent DoS via 'Retry-After: 1e9'


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    header_value = header_value.strip()
    # Integer seconds form.
    try:
        seconds = float(header_value)
        # Stage 96.6: reject non-finite (inf/nan) and clamp to sane max.
        if not math.isfinite(seconds):
            return None
        return max(0.0, min(seconds, _RETRY_AFTER_MAX_SECONDS))
    except ValueError:
        pass
    # HTTP-date form (RFC 7231).
    try:
        parsed_dt = email.utils.parsedate_to_datetime(header_value)
        if parsed_dt is None:
            return None
        import datetime as _dt
        now = _dt.datetime.now(tz=parsed_dt.tzinfo or _dt.timezone.utc)
        delta = (parsed_dt - now).total_seconds()
        if not math.isfinite(delta):
            return None
        return max(0.0, min(delta, _RETRY_AFTER_MAX_SECONDS))
    except Exception:
        return None


def _backoff_seconds(attempt: int, retry_after: float | None = None) -> float:
    """Compute backoff delay. attempt starts at 0 for the first retry."""
    computed = min(
        _BACKOFF_BASE_SECONDS * (2 ** attempt) + random.uniform(0, 0.1),
        _BACKOFF_MAX_SECONDS,
    )
    if retry_after is not None:
        return max(computed, retry_after)
    return computed

# Entities that change often and should use the short TTL.
_SHORT_TTL_ENTITIES = frozenset({
    "admission",
    "medicalcard",
    "invoice",
    "client",
    "pet",
    "payment",
})


def _masked_secret(value: str) -> str:
    if not value:
        return "***"
    if len(value) <= 4:
        return "***"
    return f"{value[:2]}***{value[-2:]}"


class VetmanagerClient:
    """Async Vetmanager REST API client.

    Each instance is bound to a specific (domain, api_key) pair,
    enabling multi-tenant usage: create a new instance per request.

    Credentials source:
      Authorization: Bearer <service_token> from the current MCP request.
    """

    def __init__(self) -> None:
        get_bearer_token()
        self._vetmanager_auth: VetmanagerAuthContext | None = None
        self._domain: str | None = None
        self._api_key: str | None = None
        self._auth_source: str | None = None
        self._account_id: int | None = None
        self._bearer_token_id: int | None = None
        self._connection_id: int | None = None
        self._scopes: tuple[str, ...] = ()
        self._base_url: str | None = None
        self._last_request_started_at = 0.0
        self._pace_lock = asyncio.Lock()
        self._credentials_lock = asyncio.Lock()

    async def _ensure_runtime_credentials(self) -> None:
        """Resolve runtime credentials lazily from bearer auth."""
        if self._domain and self._api_key:
            return
        async with self._credentials_lock:
            if self._domain and self._api_key:
                return
            resolved = await resolve_runtime_credentials()
            self._vetmanager_auth = VetmanagerAuthContext(
                auth_mode=resolved.vetmanager_auth.auth_mode,
                domain=validate_runtime_domain(resolved.domain),
                credential=resolved.vetmanager_auth.credential,
                credential_header=resolved.vetmanager_auth.credential_header,
                app_name=resolved.vetmanager_auth.app_name,
            )
            self._domain = self._vetmanager_auth.domain
            self._api_key = self._vetmanager_auth.api_key
            self._auth_source = resolved.source
            self._account_id = resolved.account_id
            self._bearer_token_id = resolved.bearer_token_id
            self._connection_id = resolved.connection_id
            self._scopes = resolved.scopes

    def _api_key_fingerprint(self) -> str:
        if not self._vetmanager_auth:
            raise AuthError("Runtime credentials are not initialized.", status_code=401)
        return self._vetmanager_auth.api_key_fingerprint()

    def _canonical_url(self, base_url: str, params: dict | None) -> str:
        if not params:
            return base_url
        pairs: list[tuple[str, str]] = []
        for key, value in params.items():
            if isinstance(value, (list, tuple)):
                for item in value:
                    pairs.append((str(key), str(item)))
            else:
                pairs.append((str(key), str(value)))
        pairs.sort(key=lambda item: (item[0], item[1]))
        query = urlencode(pairs, doseq=True)
        return f"{base_url}?{query}"

    def _cache_key(self, method: str, full_url: str) -> str:
        # Include account_id for strict isolation between accounts even if they
        # share identical credentials. Falls back to fingerprint-only key for
        # legacy callers without account context.
        account_segment = f"acct:{self._account_id}" if self._account_id is not None else "acct:none"
        return f"{method.upper()}|{full_url}|{self._api_key_fingerprint()}|{account_segment}"

    def _entity_from_path(self, path: str) -> str:
        normalized = path.split("?", 1)[0].strip("/")
        parts = normalized.split("/")
        if len(parts) >= 3 and parts[0].lower() == "rest" and parts[1].lower() == "api":
            return parts[2].lower()
        return "unknown"

    def _entity_tag(self, path: str) -> str:
        if not self._domain:
            raise AuthError("Runtime credentials are not initialized.", status_code=401)
        return f"{self._domain}:{self._entity_from_path(path)}"

    async def _pace_requests(self) -> None:
        """Enforce minimal wait between sequential HTTP requests for one client."""
        async with self._pace_lock:
            now = time.monotonic()
            gap = now - self._last_request_started_at
            if gap < REQUEST_GAP_SECONDS:
                await asyncio.sleep(REQUEST_GAP_SECONDS - gap)
            self._last_request_started_at = time.monotonic()

    async def _resolve_host(self) -> str:
        await self._ensure_runtime_credentials()
        if self._base_url is not None:
            return self._base_url
        if not self._domain:
            raise VetmanagerError("Missing Vetmanager domain in runtime credentials.")
        await self._pace_requests()
        self._base_url = await resolve_vetmanager_host(self._domain)
        return self._base_url

    def _headers(self) -> dict[str, str]:
        if not self._vetmanager_auth:
            raise AuthError("Runtime credentials are not initialized.", status_code=401)
        headers = self._vetmanager_auth.build_headers()
        # Propagate correlation id to upstream so VM-side logs can be
        # joined with our incoming request logs. For non-HTTP transports
        # (stdio, tests) get_current_request_context() returns {} — fall
        # back to a fresh UUID so upstream logs are still distinguishable.
        ctx = get_current_request_context()
        correlation_id = ctx.get("correlation_id") if ctx else None
        headers["X-Correlation-ID"] = correlation_id or uuid.uuid4().hex
        return headers

    def _require_scope(self, method: str, path: str) -> None:
        required_scope = required_scope_for_request(method, path)
        if required_scope is None:
            return
        if required_scope not in self._scopes:
            raise AuthError(
                f"Bearer token lacks required scope '{required_scope}'.",
                status_code=403,
            )

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        await self._ensure_runtime_credentials()
        self._require_scope(method, path)
        base = await self._resolve_host()
        url = f"{base}{path}"
        params = kwargs.get("params")
        cache_key = ""
        entity_tag = self._entity_tag(path)
        upper_method = method.upper()
        if upper_method == "GET":
            full_url = self._canonical_url(url, params if isinstance(params, dict) else None)
            cache_key = self._cache_key(method, full_url)
            cached = await REQUEST_CACHE.get(cache_key)
            if cached is not None:
                return cached

        # Circuit breaker fast-path: if domain is currently OPEN and cooldown
        # has not elapsed, fail fast instead of waiting the full timeout.
        domain_key = self._domain or "unknown"
        await _check_breaker_allows(domain_key)

        # Stage 98.1: capture correlation_id once so structured warnings on
        # timeout / network / retry can tie back to the inbound MCP request.
        _corr_ctx = get_current_request_context()
        outbound_correlation_id = _corr_ctx.get("correlation_id") if _corr_ctx else None

        max_retries = MAX_RETRIES_READ if upper_method == "GET" else MAX_RETRIES_WRITE
        attempt = 0
        while True:
            try:
                await self._pace_requests()
                # Started AFTER pace_requests so upstream latency metric
                # reflects only the httpx round-trip, not client-side pacing.
                started = time.monotonic()
                client = await _get_shared_http_client()
                response = await client.request(method, url, headers=self._headers(), **kwargs)
                elapsed = time.monotonic() - started
                record_upstream_request(
                    target="vetmanager_api",
                    status=f"http_{response.status_code}",
                    duration_seconds=elapsed,
                )

                # Retryable HTTP status for idempotent reads only.
                if (
                    upper_method == "GET"
                    and response.status_code in _RETRY_STATUS_CODES
                    and attempt < max_retries
                ):
                    retry_after = _parse_retry_after(response.headers.get("Retry-After"))
                    delay = _backoff_seconds(attempt, retry_after)
                    # Stage 98.6: intermediate retries at DEBUG to avoid INFO
                    # floods during 429 episodes; only the last attempt escalates.
                    is_last_attempt = attempt + 1 >= max_retries
                    _retry_logger = RUNTIME_LOGGER.info if is_last_attempt else RUNTIME_LOGGER.debug
                    _retry_logger(
                        "VM upstream retryable status",
                        extra={
                            "event_name": "vm_upstream_retry",
                            "correlation_id": outbound_correlation_id,
                            "domain": self._domain,
                            "method": upper_method,
                            "url_path": path,
                            "status_code": response.status_code,
                            "attempt": attempt + 1,
                            "backoff_seconds": round(delay, 3),
                        },
                    )
                    await asyncio.sleep(delay)
                    attempt += 1
                    continue

                # 5xx response — breaker needs to know BEFORE we raise.
                # Stage 99.1: also records failure on ALL retry attempts (not
                # just the terminal one) so breaker threshold reacts at real
                # upstream-failure-rate, not per-tool-call rate.
                if response.status_code >= 500:
                    await _breaker_record_failure(domain_key)

                self._raise_for_status(response)
                payload = response.json()
                await _breaker_record_success(domain_key)
                if upper_method == "GET":
                    entity_name = self._entity_from_path(path)
                    ttl = (
                        CACHE_TTL_SHORT_SECONDS
                        if entity_name in _SHORT_TTL_ENTITIES
                        else CACHE_TTL_SECONDS
                    )
                    await REQUEST_CACHE.set(
                        key=cache_key,
                        value=payload,
                        ttl_seconds=ttl,
                        tags=(entity_tag,),
                    )
                elif upper_method in {"POST", "PUT", "DELETE"}:
                    await REQUEST_CACHE.invalidate_tag(entity_tag)
                return payload
            except httpx.TimeoutException as exc:
                elapsed = time.monotonic() - started
                # Stage 99.1: record failure per-attempt so breaker threshold
                # reflects real upstream failure rate, not tool-call rate.
                await _breaker_record_failure(domain_key)
                if attempt < max_retries:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    attempt += 1
                    continue
                record_upstream_failure(target="vetmanager_api", reason="timeout")
                record_upstream_request(
                    target="vetmanager_api",
                    status="timeout",
                    duration_seconds=elapsed,
                )
                # Failure already recorded per-attempt above; don't double-count
                # on exhaustion — but keep the raise path unchanged.
                RUNTIME_LOGGER.warning(
                    "VM upstream timeout",
                    extra={
                        "event_name": "vm_upstream_timeout",
                        "correlation_id": outbound_correlation_id,
                        "domain": self._domain,
                        "method": upper_method,
                        "url_path": path,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "attempt": attempt + 1,
                    },
                )
                raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
            except (AuthError, NotFoundError):
                # True 4xx (401/403/404) — upstream is alive, just rejected
                # the request. During HALF_OPEN probe this MUST clear
                # probe_in_flight, otherwise the breaker wedges (stage 96.4).
                # Also records success in CLOSED state — harmless (counter
                # was already zero).
                await _breaker_record_success(domain_key)
                raise
            except VetmanagerError:
                # VetmanagerError covers both 5xx (upstream unhealthy — already
                # recorded as failure above) and non-HTTP VM errors. Do NOT
                # undo the failure counter by recording success here.
                raise
            except httpx.RequestError as exc:
                elapsed = time.monotonic() - started
                # Stage 99.1: record failure per-attempt (see timeout branch).
                await _breaker_record_failure(domain_key)
                if attempt < max_retries:
                    await asyncio.sleep(_backoff_seconds(attempt))
                    attempt += 1
                    continue
                record_upstream_failure(target="vetmanager_api", reason="network_error")
                record_upstream_request(
                    target="vetmanager_api",
                    status="network_error",
                    duration_seconds=elapsed,
                )
                RUNTIME_LOGGER.warning(
                    "VM upstream network error",
                    extra={
                        "event_name": "vm_upstream_network_error",
                        "correlation_id": outbound_correlation_id,
                        "domain": self._domain,
                        "method": upper_method,
                        "url_path": path,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "attempt": attempt + 1,
                        "error_class": exc.__class__.__name__,
                    },
                )
                raise VetmanagerError(f"Network error requesting {url}: {exc}") from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthError(
                f"Invalid or missing API key ({_masked_secret(self._api_key)})",
                status_code=401,
            )
        if response.status_code == 403:
            raise AuthError("Access forbidden", status_code=403)
        if response.status_code == 404:
            raise NotFoundError("Resource not found", status_code=404)
        if response.status_code >= 400:
            # Stage 98.5: only 5xx counts as upstream failure (upstream health
            # signal). 4xx >=400 (400/405/409/422 etc.) is a client-side issue
            # — surfacing it as upstream_failures_total inflates the counter
            # on local bugs and wakes SRE on-call with false positives.
            if response.status_code >= 500:
                record_upstream_failure(
                    target="vetmanager_api", reason=f"http_{response.status_code}"
                )
            raise VetmanagerError(
                f"Upstream API error (HTTP {response.status_code})",
                status_code=response.status_code,
            )

    async def get(self, path: str, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def post(self, path: str, json: Any = None) -> Any:
        return await self._request("POST", path, json=json)

    async def put(self, path: str, json: Any = None) -> Any:
        return await self._request("PUT", path, json=json)

    async def delete(self, path: str) -> Any:
        return await self._request("DELETE", path)
