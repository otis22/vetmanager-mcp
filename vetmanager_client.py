import asyncio
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx

from exceptions import (
    AuthError,
    NotFoundError,
    VetmanagerError,
    VetmanagerTimeoutError,
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
# Stage 103d BC note: the `_BREAKER_*` names below are re-exports of the
# canonical constants in `vm_transport.breaker`. They are snapshots — the
# breaker logic itself reads `vm_transport.breaker.BREAKER_*` at call time,
# so tests that want to override thresholds must patch those module
# attributes directly (`monkeypatch.setattr("vm_transport.breaker.BREAKER_COOLDOWN_SECONDS", ...)`),
# not the re-exported underscore names here.
#
# Stage 114b policy (2026-04-19): **KEEP** — explicit owner decision.
# Rationale: these underscore re-exports serve an active test-patch
# surface (stage91/96/101/105 tests read them as reference values).
# Stage 113.1 migrated runtime to `breaker_failure_threshold()` accessor
# so the snapshot-vs-live divergence is documented + tested.
# Stage 113.1 also documents that runtime reads go through accessors,
# not through these re-exports. Removal would touch 5+ test files;
# ROI low until a next-generation refactor.
from vm_transport.breaker import (
    BREAKER_COOLDOWN_SECONDS as _BREAKER_COOLDOWN_SECONDS,
    BREAKER_FAILURE_THRESHOLD as _BREAKER_FAILURE_THRESHOLD,
    BREAKER_WINDOW_SECONDS as _BREAKER_WINDOW_SECONDS,
    DomainBreaker as _DomainBreaker,
    _breakers,
    _breakers_global_lock,
    breaker_record_failure as _breaker_record_failure,
    breaker_record_success as _breaker_record_success,
    check_breaker_allows as _check_breaker_allows,
    force_breaker_open,
    get_breaker as _get_breaker,
    get_breaker_state,
    reset_breakers,
)
from vm_transport.cache_policy import (
    CACHE_TTL_SECONDS,
    CACHE_TTL_SHORT_SECONDS,
    SHORT_TTL_ENTITIES as _SHORT_TTL_ENTITIES,
    entity_from_path as _entity_from_path_fn,
    ttl_for_entity,
)
from vm_transport.pool import (
    HTTP_LIMITS as _HTTP_LIMITS,
    REQUEST_TIMEOUTS as _REQUEST_TIMEOUTS,
    _shared_http_client_lock,
    _shared_http_clients,
    current_loop_key as _current_loop_key,
    get_shared_http_client as _get_shared_http_client,
    reset_shared_http_client,
)
from vm_transport.retry import (
    BACKOFF_BASE_SECONDS as _BACKOFF_BASE_SECONDS,
    BACKOFF_MAX_SECONDS as _BACKOFF_MAX_SECONDS,
    MAX_RETRIES_READ,
    MAX_RETRIES_WRITE,
    RETRY_AFTER_MAX_SECONDS as _RETRY_AFTER_MAX_SECONDS,
    RETRY_STATUS_CODES as _RETRY_STATUS_CODES,
    backoff_seconds as _backoff_seconds,
    parse_retry_after as _parse_retry_after,
)

# Stage 108.9: legacy REQUEST_TIMEOUT removed — actual timeouts live in
# vm_transport/pool.py::REQUEST_TIMEOUTS (connect=5, read=20, write=10, pool=2).
REQUEST_GAP_SECONDS = 0.05

# Shared httpx.AsyncClient pool (stage 99.4) lives in vm_transport.pool —
# re-exported above.


# ── Public test-helpers (stage 101.2, rewritten in 106.7) ───────────────────

def get_shared_http_client_state() -> dict:
    """Return an aggregate snapshot of the per-loop shared-client pool.

    Stage 106.7 (H21 fix): previously read a dead module-level sentinel
    (`_shared_http_client`, always None after the stage 103d split) and
    returned misleading `{"exists": False, "closed": True}` even when
    N live per-loop clients existed. Now reports observable facts about
    the real `_shared_http_clients` dict:

    - `loop_keys`: loop ids registered in the pool.
    - `open_count`: number of non-closed `AsyncClient` instances.
    - `current_loop_registered`: whether the running loop has a client.
    """
    current_key = _current_loop_key()
    return {
        "loop_keys": list(_shared_http_clients.keys()),
        "open_count": sum(1 for c in _shared_http_clients.values() if not c.is_closed),
        "current_loop_registered": current_key in _shared_http_clients,
    }


# Circuit breaker (per-domain) lives in vm_transport.breaker — see
# import block above. Re-exports cover: _DomainBreaker, _breakers,
# _breakers_global_lock, _get_breaker, _check_breaker_allows,
# _breaker_record_success, _breaker_record_failure, get_breaker_state,
# force_breaker_open, reset_breakers, _BREAKER_* constants.


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
        # Stage 103d: thin wrapper over vm_transport.cache_policy.entity_from_path
        # kept as an instance method for back-compat with tests that call it via
        # the client; the free function is the canonical location.
        return _entity_from_path_fn(path)

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
        # Stage 106.1 (F2 fix): `_check_breaker_allows` above may have
        # transitioned to HALF_OPEN with probe_in_flight=True. If the retry
        # loop terminates via an UNEXPECTED exception (asyncio CancelledError
        # on task cancel, shutdown, KeyboardInterrupt), none of the
        # record_success/record_failure branches runs and probe_in_flight
        # stays True forever — wedging the domain in HALF_OPEN.
        # Flag gets set True after any normal branch ran its breaker hook;
        # finally records failure if nothing ran (unexpected exit).
        _breaker_resolved = False
        try:
            while True:
                # Stage 105.2 (B2 fix): re-check breaker before each retry attempt.
                # If a concurrent request tripped the breaker between our initial
                # check (above the while loop) and this retry, abort immediately
                # with VetmanagerUpstreamUnavailable instead of wasting more
                # round-trips against a known-dead upstream.
                if attempt > 0:
                    await _check_breaker_allows(domain_key)
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
                        # Stage 112.5 (super-review 2026-04-19): all retry
                        # decisions at DEBUG to avoid false alert noise for
                        # self-healing retries. Terminal failure still
                        # escalates at WARNING via vm_upstream_timeout /
                        # vm_upstream_network_error at the raise site.
                        # Stage 112.3: emit entity instead of full path to
                        # avoid leaking customer IDs into log aggregation.
                        RUNTIME_LOGGER.debug(
                            "VM upstream retryable status",
                            extra={
                                "event_name": "vm_upstream_retry",
                                "correlation_id": outbound_correlation_id,
                                "domain": self._domain,
                                "method": upper_method,
                                "entity": _entity_from_path_fn(path),
                                "status_code": response.status_code,
                                "attempt": attempt + 1,
                                "backoff_seconds": round(delay, 3),
                            },
                        )
                        await asyncio.sleep(delay)
                        attempt += 1
                        continue

                    # 5xx response — breaker needs to know BEFORE we raise.
                    if response.status_code >= 500:
                        await _breaker_record_failure(domain_key)
                        _breaker_resolved = True

                    self._raise_for_status(response)
                    payload = response.json()
                    await _breaker_record_success(domain_key)
                    _breaker_resolved = True
                    if upper_method == "GET":
                        # TTLs read through module-level names so existing tests
                        # that monkey-patch `vetmanager_client.CACHE_TTL_*` keep
                        # working. Stage 103d: cache_policy.ttl_for_entity is
                        # the canonical location, but we don't route through it
                        # here to preserve the patch surface.
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
                        # Stage 107.10: DEBUG log for intermediate retries so
                        # latency investigations can see how many attempts
                        # timed out and at which backoff each.
                        # Stage 112.3 (super-review 2026-04-19): emit entity
                        # name instead of full path to avoid leaking customer
                        # IDs (e.g. /rest/api/client/12345 → "client") into
                        # log aggregation. Full path is reconstructable via
                        # correlation_id join if debugging needs it.
                        RUNTIME_LOGGER.debug(
                            "VM upstream timeout on retry attempt",
                            extra={
                                "event_name": "vm_upstream_timeout_retry",
                                "correlation_id": outbound_correlation_id,
                                "domain": self._domain,
                                "method": upper_method,
                                "entity": _entity_from_path_fn(path),
                                "attempt": attempt + 1,
                                "elapsed_ms": round(elapsed * 1000, 2),
                            },
                        )
                        await asyncio.sleep(_backoff_seconds(attempt))
                        attempt += 1
                        continue
                    # Stage 105.2 (B2 fix): ONE breaker failure per logical call.
                    await _breaker_record_failure(domain_key)
                    _breaker_resolved = True
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
                            "correlation_id": outbound_correlation_id,
                            "domain": self._domain,
                            "method": upper_method,
                            "entity": _entity_from_path_fn(path),
                            "elapsed_ms": round(elapsed * 1000, 2),
                            "attempt": attempt + 1,
                        },
                    )
                    raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
                except (AuthError, NotFoundError):
                    # True 4xx (401/403/404) — upstream is alive, just rejected
                    # the request. During HALF_OPEN probe this MUST clear
                    # probe_in_flight (stage 96.4).
                    await _breaker_record_success(domain_key)
                    _breaker_resolved = True
                    raise
                except VetmanagerError:
                    # 5xx / non-HTTP VM errors already recorded failure above;
                    # _breaker_resolved was set there.
                    raise
                except httpx.RequestError as exc:
                    elapsed = time.monotonic() - started
                    if attempt < max_retries:
                        await asyncio.sleep(_backoff_seconds(attempt))
                        attempt += 1
                        continue
                    # Stage 105.2 (B2 fix): one breaker failure per logical call.
                    await _breaker_record_failure(domain_key)
                    _breaker_resolved = True
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
                            "entity": _entity_from_path_fn(path),
                            "elapsed_ms": round(elapsed * 1000, 2),
                            "attempt": attempt + 1,
                            "error_class": exc.__class__.__name__,
                        },
                    )
                    raise VetmanagerError(f"Network error requesting {url}: {exc}") from exc
        finally:
            # Stage 106.1 (F2 fix): clear breaker probe_in_flight on any
            # UNEXPECTED exit (CancelledError, shutdown, KeyboardInterrupt).
            # Normal branches set `_breaker_resolved = True` after running
            # their record_success/record_failure hook.
            if not _breaker_resolved:
                await _breaker_record_failure(domain_key)

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
