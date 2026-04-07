"""Services for saving and validating Vetmanager account connections."""

from __future__ import annotations

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthError, HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_resolver import resolve_vetmanager_host as _resolve_host_via_billing
from domain_validation import validate_domain as _validate_domain
from storage_models import CONNECTION_STATUS_ACTIVE, CONNECTION_STATUS_DISABLED, VetmanagerConnection
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    resolve_vetmanager_credentials,
)

REQUEST_TIMEOUT = 30.0

INTEGRATION_HEALTH_ACTIVE = "active"
INTEGRATION_HEALTH_INVALID = "invalid"
INTEGRATION_HEALTH_REAUTH_REQUIRED = "reauth_required"
INTEGRATION_HEALTH_UNKNOWN = "unknown"
TOKEN_AUTH_APP_NAME = "vetmanager-mcp"


async def resolve_vetmanager_host(domain: str) -> str:
    """Resolve normalized clinic domain into an allowlisted HTTPS host."""
    normalized_domain = _validate_domain(domain.strip())
    return await _resolve_host_via_billing(normalized_domain, max_retries=0)


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


def _safe_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return ""
    detail = payload.get("detail")
    title = payload.get("title")
    if isinstance(detail, str) and detail.strip():
        return detail.strip()
    if isinstance(title, str) and title.strip():
        return title.strip()
    return ""


async def exchange_user_token(
    domain: str,
    *,
    login: str,
    password: str,
) -> tuple[str, str]:
    """Exchange login/password into a Vetmanager user token."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_login = login.strip()
    normalized_password = password.strip()
    if not normalized_login or not normalized_password:
        raise AuthError("Invalid Vetmanager login or password.", status_code=401)

    resolved_host = await resolve_vetmanager_host(normalized_domain)
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            response = await http.post(
                f"{resolved_host}/token_auth.php",
                headers={
                    "Accept": "application/json",
                },
                files={
                    "login": (None, normalized_login),
                    "password": (None, normalized_password),
                    "app_name": (None, TOKEN_AUTH_APP_NAME),
                },
            )
        except httpx.TimeoutException as exc:
            raise VetmanagerTimeoutError("Vetmanager authorization timed out.") from exc
        except httpx.RequestError as exc:
            raise VetmanagerError("Vetmanager authorization is temporarily unavailable.") from exc

    if response.status_code == 401:
        raise AuthError("Invalid Vetmanager login or password.", status_code=401)
    if response.status_code == 403:
        raise AuthError(
            "Vetmanager login/password authorization is disabled or unavailable for this clinic. Use API key or verify clinic settings.",
            status_code=403,
        )
    if response.status_code >= 400:
        detail = _safe_error_detail(response)
        raise VetmanagerError(
            (
                f"Vetmanager authorization failed with status {response.status_code}."
                if not detail
                else f"Vetmanager authorization failed with status {response.status_code}. {detail}"
            ),
            status_code=response.status_code,
        )

    token = _extract_user_token(response.json().get("data"))
    if not token:
        raise VetmanagerError(
            "Vetmanager authorization response did not contain a user token. Use API key or verify clinic settings."
        )
    return resolved_host, token


async def validate_user_token_connection(
    domain: str,
    user_token: str,
    *,
    app_name: str = TOKEN_AUTH_APP_NAME,
    resolved_host: str | None = None,
) -> str:
    """Validate domain+user_token pair and return resolved Vetmanager host."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_user_token = user_token.strip()
    normalized_app_name = app_name.strip()
    if not normalized_user_token:
        raise AuthError("Invalid Vetmanager user token.", status_code=401)
    if not normalized_app_name:
        raise AuthError("Invalid Vetmanager app name.", status_code=401)

    resolved_host = resolved_host or await resolve_vetmanager_host(normalized_domain)
    async with httpx.AsyncClient(timeout=httpx.Timeout(REQUEST_TIMEOUT)) as http:
        try:
            probe = await http.get(
                f"{resolved_host}/rest/api/user",
                params={"limit": 1, "offset": 0},
                headers={
                    "X-USER-TOKEN": normalized_user_token,
                    "X-APP-NAME": normalized_app_name,
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
                VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
            )
        )
    ).scalars().all()
    for existing in existing_connections:
        existing.status = CONNECTION_STATUS_DISABLED


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
        status=CONNECTION_STATUS_ACTIVE,
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
    app_name: str = TOKEN_AUTH_APP_NAME,
    encryption_key: str | None = None,
) -> VetmanagerConnection:
    """Validate and persist active user_token connection for one account."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_user_token = user_token.strip()
    normalized_app_name = app_name.strip()
    await validate_user_token_connection(
        normalized_domain,
        normalized_user_token,
        app_name=normalized_app_name,
    )
    await _disable_existing_active_connections(session, account_id=account_id)

    connection = VetmanagerConnection(
        account_id=account_id,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status=CONNECTION_STATUS_ACTIVE,
        domain=normalized_domain,
    )
    connection.set_credentials(
        {
            "domain": normalized_domain,
            "user_token": normalized_user_token,
            "app_name": normalized_app_name,
        },
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
    login: str,
    password: str,
    encryption_key: str | None = None,
) -> VetmanagerConnection:
    """Exchange login/password into a user token and persist token-only connection."""
    normalized_domain = _validate_domain(domain.strip())
    resolved_host, user_token = await exchange_user_token(
        normalized_domain,
        login=login,
        password=password,
    )
    await validate_user_token_connection(
        normalized_domain,
        user_token,
        app_name=TOKEN_AUTH_APP_NAME,
        resolved_host=resolved_host,
    )
    await _disable_existing_active_connections(session, account_id=account_id)

    connection = VetmanagerConnection(
        account_id=account_id,
        auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
        status=CONNECTION_STATUS_ACTIVE,
        domain=normalized_domain,
    )
    connection.set_credentials(
        {
            "domain": normalized_domain,
            "user_token": user_token,
            "app_name": TOKEN_AUTH_APP_NAME,
        },
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
            await validate_user_token_connection(
                auth_context.domain,
                auth_context.credential,
                app_name=auth_context.app_name or TOKEN_AUTH_APP_NAME,
            )
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
