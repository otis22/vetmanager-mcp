import logging
import asyncio
import hashlib
import time
import uuid
from typing import Any
from urllib.parse import urlencode

import httpx

from exceptions import (
    AuthError,
    HostResolutionError,
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

REQUEST_TIMEOUT = 30.0
REQUEST_GAP_SECONDS = 0.05
MAX_RETRIES = 1
# Default cache TTL for stable reference data (breeds, cities, goods, etc.).
CACHE_TTL_SECONDS = 900.0
# Short TTL for frequently-updated entities: admissions, medical cards, invoices, clients.
# Keeps data fresh while still reducing redundant API calls within a single session.
CACHE_TTL_SHORT_SECONDS = 60.0

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
        if method.upper() == "GET":
            full_url = self._canonical_url(url, params if isinstance(params, dict) else None)
            cache_key = self._cache_key(method, full_url)
            cached = await REQUEST_CACHE.get(cache_key)
            if cached is not None:
                return cached

        for attempt in range(MAX_RETRIES + 1):
            try:
                await self._pace_requests()
                # Started AFTER pace_requests so the upstream latency metric
                # reflects only the httpx round-trip, not our own client-side
                # pacing delay (REQUEST_GAP_SECONDS serialization).
                started = time.monotonic()
                timeout = httpx.Timeout(REQUEST_TIMEOUT)
                async with httpx.AsyncClient(timeout=timeout) as http:
                    response = await http.request(method, url, headers=self._headers(), **kwargs)
                    elapsed = time.monotonic() - started
                    record_upstream_request(
                        target="vetmanager_api",
                        status=f"http_{response.status_code}",
                        duration_seconds=elapsed,
                    )
                    self._raise_for_status(response)
                    payload = response.json()
                    upper_method = method.upper()
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
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
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
                        "method": method.upper(),
                        "url_path": path,
                        "elapsed_ms": round(elapsed * 1000, 2),
                        "attempt": attempt + 1,
                    },
                )
                raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
            except (AuthError, NotFoundError, VetmanagerError):
                raise
            except httpx.RequestError as exc:
                elapsed = time.monotonic() - started
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
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
                        "method": method.upper(),
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
