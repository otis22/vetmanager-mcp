"""Services for saving and validating Vetmanager account connections."""

from __future__ import annotations

from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthError, HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from runtime_auth import _validate_domain
from storage_models import VetmanagerConnection
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    resolve_vetmanager_credentials,
)

BILLING_API = "https://billing-api.vetmanager.cloud/host/{domain}"
REQUEST_TIMEOUT = 30.0
ALLOWED_HOST_SUFFIXES = ("vetmanager.cloud", "vetmanager2.ru")

INTEGRATION_HEALTH_ACTIVE = "active"
INTEGRATION_HEALTH_INVALID = "invalid"
INTEGRATION_HEALTH_REAUTH_REQUIRED = "reauth_required"
INTEGRATION_HEALTH_UNKNOWN = "unknown"


def _validate_resolved_host(host: str, domain: str) -> str:
    parsed = urlparse(host)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        raise HostResolutionError(f"Resolved host must use HTTPS for domain '{domain}'.")
    if not any(hostname == suffix or hostname.endswith(f".{suffix}") for suffix in ALLOWED_HOST_SUFFIXES):
        raise HostResolutionError(f"Resolved host is not allowlisted for domain '{domain}'.")
    return host.rstrip("/")


async def resolve_vetmanager_host(domain: str) -> str:
    """Resolve normalized clinic domain into an allowlisted HTTPS host."""
    normalized_domain = _validate_domain(domain.strip())
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            billing_response = await http.get(BILLING_API.format(domain=normalized_domain))
            billing_response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError("Vetmanager host resolution timed out.") from exc
        except httpx.RequestError as exc:
            raise VetmanagerError("Vetmanager host resolution is temporarily unavailable.") from exc

    data = billing_response.json()
    host = data.get("data", {}).get("url") or data.get("url")
    if not host:
        raise HostResolutionError(
            f"Unexpected billing API response for domain '{normalized_domain}'."
        )
    if not host.startswith("http"):
        host = f"https://{host}"
    return _validate_resolved_host(host, normalized_domain)


async def validate_domain_api_key_connection(
    domain: str,
    api_key: str,
    *,
    resolved_host: str | None = None,
) -> str:
    """Validate domain+api_key pair and return resolved Vetmanager host."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_api_key = api_key.strip()
    if not normalized_api_key:
        raise AuthError("Invalid Vetmanager API key.", status_code=401)

    resolved_host = resolved_host or await resolve_vetmanager_host(normalized_domain)
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            probe = await http.get(
                f"{resolved_host}/rest/api/client",
                params={"limit": 1, "offset": 0},
                headers={
                    "X-REST-API-KEY": normalized_api_key,
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError("Vetmanager connection test timed out.") from exc
        except httpx.RequestError as exc:
            raise VetmanagerError("Vetmanager connection test is temporarily unavailable.") from exc

    if probe.status_code == 401:
        raise AuthError("Invalid Vetmanager API key.", status_code=401)
    if probe.status_code >= 400:
        raise VetmanagerError(
            f"Vetmanager connection test failed with status {probe.status_code}.",
            status_code=probe.status_code,
        )
    return resolved_host


def _extract_user_token(payload: object) -> str | None:
    """Extract a usable user token from a token_auth.php response payload."""
    if isinstance(payload, str):
        return payload.strip() or None
    if isinstance(payload, dict):
        for key in ("token", "user_token", "api_key", "key"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


async def exchange_user_token(
    domain: str,
    *,
    api_key: str,
    login: str,
    password: str,
) -> tuple[str, str]:
    """Exchange login/password into a Vetmanager user token."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_api_key = api_key.strip()
    normalized_login = login.strip()
    normalized_password = password.strip()
    if not normalized_api_key or not normalized_login or not normalized_password:
        raise AuthError("Invalid Vetmanager login, password or API key.", status_code=401)

    resolved_host = await resolve_vetmanager_host(normalized_domain)
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            response = await http.post(
                f"{resolved_host}/token_auth.php",
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-REST-API-KEY": normalized_api_key,
                },
                data={
                    "login": normalized_login,
                    "password": normalized_password,
                },
            )
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError("Vetmanager authorization timed out.") from exc
        except httpx.RequestError as exc:
            raise VetmanagerError("Vetmanager authorization is temporarily unavailable.") from exc

    if response.status_code == 401:
        raise AuthError("Invalid Vetmanager login, password or API key.", status_code=401)
    if response.status_code >= 400:
        raise VetmanagerError(
            f"Vetmanager authorization failed with status {response.status_code}.",
            status_code=response.status_code,
        )

    token = _extract_user_token(response.json().get("data"))
    if not token:
        raise VetmanagerError("Vetmanager authorization response did not contain a user token.")
    return resolved_host, token


async def validate_user_token_connection(
    domain: str,
    user_token: str,
    *,
    resolved_host: str | None = None,
) -> str:
    """Validate domain+user_token pair and return resolved Vetmanager host."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_user_token = user_token.strip()
    if not normalized_user_token:
        raise AuthError("Invalid Vetmanager user token.", status_code=401)

    resolved_host = resolved_host or await resolve_vetmanager_host(normalized_domain)
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            probe = await http.get(
                f"{resolved_host}/rest/api/user",
                params={"limit": 1, "offset": 0},
                headers={
                    "X-REST-API-KEY": normalized_user_token,
                    "Accept": "application/json",
                },
            )
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError("Vetmanager user-token validation timed out.") from exc
        except httpx.RequestError as exc:
            raise VetmanagerError("Vetmanager user-token validation is temporarily unavailable.") from exc

    if probe.status_code == 401:
        raise AuthError("Invalid Vetmanager user token.", status_code=401)
    if probe.status_code >= 400:
        raise VetmanagerError(
            f"Vetmanager user-token connection test failed with status {probe.status_code}.",
            status_code=probe.status_code,
        )
    return resolved_host


async def _disable_existing_active_connections(session: AsyncSession, *, account_id: int) -> None:
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
    await _disable_existing_active_connections(session, account_id=account_id)

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


async def save_user_token_connection(
    session: AsyncSession,
    *,
    account_id: int,
    domain: str,
    user_token: str,
    encryption_key: str | None = None,
) -> VetmanagerConnection:
    """Validate and persist active user_token connection for one account."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_user_token = user_token.strip()
    await validate_user_token_connection(normalized_domain, normalized_user_token)
    await _disable_existing_active_connections(session, account_id=account_id)

    connection = VetmanagerConnection(
        account_id=account_id,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status="active",
        domain=normalized_domain,
    )
    connection.set_credentials(
        {"domain": normalized_domain, "user_token": normalized_user_token},
        encryption_key=encryption_key,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


async def save_user_login_password_connection(
    session: AsyncSession,
    *,
    account_id: int,
    domain: str,
    api_key: str,
    login: str,
    password: str,
    encryption_key: str | None = None,
) -> VetmanagerConnection:
    """Exchange login/password into a user token and persist token-only connection."""
    normalized_domain = _validate_domain(domain.strip())
    resolved_host, user_token = await exchange_user_token(
        normalized_domain,
        api_key=api_key,
        login=login,
        password=password,
    )
    await validate_user_token_connection(
        normalized_domain,
        user_token,
        resolved_host=resolved_host,
    )
    await _disable_existing_active_connections(session, account_id=account_id)

    connection = VetmanagerConnection(
        account_id=account_id,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status="active",
        domain=normalized_domain,
    )
    connection.set_credentials(
        {"domain": normalized_domain, "user_token": user_token},
        encryption_key=encryption_key,
    )
    session.add(connection)
    await session.commit()
    await session.refresh(connection)
    return connection


async def evaluate_connection_health(
    connection: VetmanagerConnection,
    *,
    encryption_key: str | None = None,
) -> tuple[str, str]:
    """Evaluate current health of one stored Vetmanager connection."""
    auth_context = resolve_vetmanager_credentials(connection, encryption_key=encryption_key)
    try:
        if auth_context.auth_mode == VETMANAGER_AUTH_MODE_DOMAIN_API_KEY:
            await validate_domain_api_key_connection(auth_context.domain, auth_context.credential)
            return INTEGRATION_HEALTH_ACTIVE, "Integration is active."
        if auth_context.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
            await validate_user_token_connection(auth_context.domain, auth_context.credential)
            return INTEGRATION_HEALTH_ACTIVE, "Integration is active."
    except AuthError:
        if auth_context.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
            return (
                INTEGRATION_HEALTH_REAUTH_REQUIRED,
                "Stored user token is invalid. Re-authenticate to issue a fresh token.",
            )
        return INTEGRATION_HEALTH_INVALID, "Stored Vetmanager API key is invalid."
    except (HostResolutionError, VetmanagerTimeoutError, VetmanagerError):
        return (
            INTEGRATION_HEALTH_UNKNOWN,
            "Integration health could not be verified right now. Try again later.",
        )
    return INTEGRATION_HEALTH_UNKNOWN, "Integration health could not be determined."
