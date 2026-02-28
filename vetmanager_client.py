import logging
import asyncio
import hashlib
import re
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
from request_credentials import get_request_credentials

logger = logging.getLogger(__name__)

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0
REQUEST_GAP_SECONDS = 0.05
MAX_RETRIES = 1
DOMAIN_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")
CACHE_TTL_SECONDS = 900.0


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
      X-VM-Domain / X-VM-Api-Key HTTP headers from the current MCP request
      (set via mcp.json `headers` block — Variant A).
    """

    def __init__(self) -> None:
        self._domain, self._api_key = get_request_credentials()
        if not self._domain:
            raise VetmanagerError(
                "Missing Vetmanager domain. Set X-VM-Domain header in your mcp.json."
            )
        if not self._api_key:
            raise AuthError(
                "Missing Vetmanager API key. Set X-VM-Api-Key header in your mcp.json.",
                status_code=401,
            )
        if not DOMAIN_PATTERN.fullmatch(self._domain):
            raise VetmanagerError(
                "Invalid Vetmanager domain format. Use clinic subdomain like 'myclinic'."
            )
        self._base_url: str | None = None
        self._last_request_started_at = 0.0
        self._pace_lock = asyncio.Lock()

    def _api_key_fingerprint(self) -> str:
        return hashlib.sha256(self._api_key.encode("utf-8")).hexdigest()[:16]

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
        if self._base_url is not None:
            return self._base_url

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
        return {
            "X-REST-API-KEY": self._api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

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
                        await REQUEST_CACHE.set(
                            key=cache_key,
                            value=payload,
                            ttl_seconds=CACHE_TTL_SECONDS,
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
