import logging
import asyncio
import hashlib
import time
from typing import Any
from urllib.parse import urlencode, urlparse

import httpx

from exceptions import (
    AuthError,
    HostResolutionError,
    NotFoundError,
    VetmanagerError,
    VetmanagerTimeoutError,
)
from request_cache import REQUEST_CACHE
from request_auth import get_bearer_token
from runtime_auth import _validate_domain as validate_runtime_domain
from runtime_auth import resolve_runtime_credentials
from vetmanager_auth import VetmanagerAuthContext

logger = logging.getLogger(__name__)

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0
REQUEST_GAP_SECONDS = 0.05
MAX_RETRIES = 1
ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")
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
                api_key=resolved.api_key,
            )
            self._domain = self._vetmanager_auth.domain
            self._api_key = self._vetmanager_auth.api_key
            self._auth_source = resolved.source
            self._account_id = resolved.account_id
            self._bearer_token_id = resolved.bearer_token_id
            self._connection_id = resolved.connection_id

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
        return f"{method.upper()}|{full_url}|{self._api_key_fingerprint()}"

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

    def _validate_resolved_host(self, host: str) -> str:
        parsed = urlparse(host)
        hostname = (parsed.hostname or "").lower()
        if parsed.scheme != "https":
            raise HostResolutionError(
                f"Resolved host must use HTTPS for domain '{self._domain}'."
            )
        if not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
            raise HostResolutionError(
                f"Resolved host is not allowlisted for domain '{self._domain}'."
            )
        return host

    async def _resolve_host(self) -> str:
        await self._ensure_runtime_credentials()
        if self._base_url is not None:
            return self._base_url

        if not self._domain:
            raise VetmanagerError("Missing Vetmanager domain in runtime credentials.")
        url = BILLING_API.format(domain=self._domain)
        for attempt in range(MAX_RETRIES + 1):
            try:
                await self._pace_requests()
                timeout = httpx.Timeout(REQUEST_TIMEOUT)
                async with httpx.AsyncClient(timeout=timeout) as http:
                    response = await http.get(url)
                    response.raise_for_status()
                    data = response.json()
                    host = data.get("data", {}).get("url") or data.get("url")
                    if not host:
                        raise HostResolutionError(
                            f"Unexpected billing API response for domain '{self._domain}'."
                        )
                    host = host.rstrip("/")
                    if not host.startswith("http"):
                        host = f"https://{host}"
                    self._base_url = self._validate_resolved_host(host)
                    logger.debug("Resolved host for '%s': %s", self._domain, self._base_url)
                    return self._base_url
            except httpx.TimeoutException as exc:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                raise VetmanagerTimeoutError(f"Timeout resolving host for domain '{self._domain}'") from exc
            except httpx.HTTPStatusError as exc:
                raise HostResolutionError(
                    f"Billing API returned {exc.response.status_code} for domain '{self._domain}'."
                ) from exc
            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                raise VetmanagerError(
                    f"Network error resolving host for domain '{self._domain}': {exc}"
                ) from exc

    def _headers(self) -> dict[str, str]:
        if not self._vetmanager_auth:
            raise AuthError("Runtime credentials are not initialized.", status_code=401)
        return self._vetmanager_auth.build_headers()

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
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
                timeout = httpx.Timeout(REQUEST_TIMEOUT)
                async with httpx.AsyncClient(timeout=timeout) as http:
                    response = await http.request(method, url, headers=self._headers(), **kwargs)
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
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
            except (AuthError, NotFoundError, VetmanagerError):
                raise
            except httpx.RequestError as exc:
                if attempt < MAX_RETRIES:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
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
            raise VetmanagerError(
                f"API error {response.status_code}: {response.text[:200]}",
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
