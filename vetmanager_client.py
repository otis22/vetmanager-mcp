import logging
import asyncio
import email.utils
import hashlib
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

_shared_http_client: httpx.AsyncClient | None = None
_shared_http_client_lock = asyncio.Lock()


async def _get_shared_http_client() -> httpx.AsyncClient:
    """Return a process-wide singleton httpx.AsyncClient with keep-alive pool.

    Lazy-initialized on first access. Creating a fresh client per request
    costs a TLS handshake each time (~100-400ms on prod). Reuse eliminates
    that overhead and also shares the underlying connection pool.
    """
    global _shared_http_client
    client = _shared_http_client
    if client is not None and not client.is_closed:
        return client
    async with _shared_http_client_lock:
        client = _shared_http_client
        if client is not None and not client.is_closed:
            return client
        client = httpx.AsyncClient(timeout=_REQUEST_TIMEOUTS, limits=_HTTP_LIMITS)
        _shared_http_client = client
        return client


async def reset_shared_http_client() -> None:
    """Close and drop the shared client. For tests and shutdown."""
    global _shared_http_client
    async with _shared_http_client_lock:
        client = _shared_http_client
        _shared_http_client = None
    if client is not None:
        try:
            await client.aclose()
        except Exception:
            pass


# ── Circuit breaker (per-domain) ────────────────────────────────────────────

_BREAKER_FAILURE_THRESHOLD = 5
_BREAKER_WINDOW_SECONDS = 60.0
_BREAKER_COOLDOWN_SECONDS = 30.0


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
    and marks probe_in_flight when admitting the first probe after cooldown."""
    breaker = await _get_breaker(domain)
    async with breaker.lock:
        if breaker.state == "open":
            elapsed = time.monotonic() - breaker.opened_at
            if elapsed < _BREAKER_COOLDOWN_SECONDS:
                record_upstream_failure(
                    target="vetmanager_api", reason="circuit_open"
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


def _parse_retry_after(header_value: str | None) -> float | None:
    if not header_value:
        return None
    header_value = header_value.strip()
    # Integer seconds form.
    try:
        seconds = float(header_value)
        return max(0.0, seconds)
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
        return max(0.0, delta)
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
                    RUNTIME_LOGGER.info(
                        "VM upstream retryable status",
                        extra={
                            "event_name": "vm_upstream_retry",
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

                # 5xx response (either non-GET or exhausted retries) counts
                # as upstream unhealth — breaker needs to know BEFORE we raise.
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
                RUNTIME_LOGGER.warning(
                    "VM upstream timeout",
                    extra={
                        "event_name": "vm_upstream_timeout",
                        "domain": self._domain,
                        "method": upper_method,
                        "url_path": path,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "attempt": attempt + 1,
                    },
                )
                await _breaker_record_failure(domain_key)
                raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
            except (AuthError, NotFoundError, VetmanagerError):
                # Upstream 4xx and VetmanagerError do not count as breaker
                # failures — they reflect client-side issues, not upstream health.
                raise
            except httpx.RequestError as exc:
                elapsed = time.monotonic() - started
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
                        "domain": self._domain,
                        "method": upper_method,
                        "url_path": path,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "attempt": attempt + 1,
                        "error_class": exc.__class__.__name__,
                    },
                )
                await _breaker_record_failure(domain_key)
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
            record_upstream_failure(target="vetmanager_api", reason=f"http_{response.status_code}")
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
