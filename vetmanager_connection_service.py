"""Services for saving and validating Vetmanager account connections."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthError, HostResolutionError, VetmanagerError
from runtime_auth import _validate_domain
from storage_models import VetmanagerConnection
from vetmanager_auth import VETMANAGER_AUTH_MODE_DOMAIN_API_KEY

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0
ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")


def _validate_resolved_host(host: str, domain: str) -> str:
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise HostResolutionError(f"Resolved host must use HTTPS for domain '{domain}'.")
    if not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        raise HostResolutionError(f"Resolved host is not allowlisted for domain '{domain}'.")
    return host.rstrip("/")


async def validate_domain_api_key_connection(domain: str, api_key: str) -> str:
    """Validate domain+api_key pair and return resolved Vetmanager host."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_api_key = api_key.strip()
    if not normalized_api_key:
        raise AuthError("Invalid Vetmanager API key.", status_code=401)

    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        billing_response = await http.get(BILLING_API.format(domain=normalized_domain))
        billing_response.raise_for_status()
        data = billing_response.json()
        host = data.get("data", {}).get("url") or data.get("url")
        if not host:
            raise HostResolutionError(
                f"Unexpected billing API response for domain '{normalized_domain}'."
            )
        if not host.startswith("http"):
            host = f"https://{host}"
        resolved_host = _validate_resolved_host(host, normalized_domain)

        probe = await http.get(
            f"{resolved_host}/rest/api/client",
            params={"limit": 1, "offset": 0},
            headers={
                "X-REST-API-KEY": normalized_api_key,
                "Accept": "application/json",
            },
        )
        if probe.status_code == 401:
            raise AuthError("Invalid Vetmanager API key.", status_code=401)
        if probe.status_code >= 400:
            raise VetmanagerError(
                f"Vetmanager connection test failed with status {probe.status_code}.",
                status_code=probe.status_code,
            )
    return resolved_host


async def save_domain_api_key_connection(
    session: AsyncSession,
    *,
    account_id: int,
    domain: str,
    api_key: str,
    encryption_key: str | None = None,
) -> VetmanagerConnection:
    """Validate and persist active domain_api_key connection for one account."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_api_key = api_key.strip()
    await validate_domain_api_key_connection(normalized_domain, normalized_api_key)

    existing_connections = (
        await session.execute(
            select(VetmanagerConnection).where(
                VetmanagerConnection.account_id == account_id,
                VetmanagerConnection.status == "active",
            )
        )
    ).scalars().all()
    for existing in existing_connections:
        existing.status = "disabled"

    connection = VetmanagerConnection(
        account_id=account_id,
        auth_mode=VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
        status="active",
        domain=normalized_domain,
    )
    connection.set_credentials(
        {"domain": normalized_domain, "api_key": normalized_api_key},
        encryption_key=encryption_key,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection
