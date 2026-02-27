import logging
from typing import Any

import httpx

from exceptions import (
    AuthError,
    HostResolutionError,
    NotFoundError,
    VetmanagerError,
    VetmanagerTimeoutError,
)

logger = logging.getLogger(__name__)

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0


class VetmanagerClient:
    """Async Vetmanager REST API client.

    Each instance is bound to a specific (domain, api_key) pair,
    enabling multi-tenant usage: create a new instance per request.
    """

    def __init__(self, domain: str, api_key: str) -> None:
        self._domain = domain
        self._api_key = api_key
        self._base_url: str | None = None

    async def _resolve_host(self) -> str:
        if self._base_url is not None:
            return self._base_url

        url = BILLING_API.format(domain=self._domain)
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
                response = await http.get(url)
                response.raise_for_status()
                data = response.json()
                host = data.get("data", {}).get("url") or data.get("url")
                if not host:
                    raise HostResolutionError(
                        f"Unexpected billing API response for domain '{self._domain}': {data}"
                    )
                host = host.rstrip("/")
                if not host.startswith("http"):
                    host = f"https://{host}"
                self._base_url = host
                logger.debug("Resolved host for '%s': %s", self._domain, self._base_url)
                return self._base_url
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError(f"Timeout resolving host for domain '{self._domain}'") from exc
        except httpx.HTTPStatusError as exc:
            raise HostResolutionError(
                f"Billing API returned {exc.response.status_code} for domain '{self._domain}'"
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
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as http:
                response = await http.request(method, url, headers=self._headers(), **kwargs)
                self._raise_for_status(response)
                return response.json()
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError(f"Request to {url} timed out") from exc
        except httpx.HTTPStatusError:
            raise
        except (AuthError, NotFoundError, VetmanagerError):
            raise
        except httpx.RequestError as exc:
            raise VetmanagerError(f"Network error requesting {url}: {exc}") from exc

    def _raise_for_status(self, response: httpx.Response) -> None:
        if response.status_code == 401:
            raise AuthError("Invalid or missing API key", status_code=401)
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
