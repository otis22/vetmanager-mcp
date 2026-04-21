"""Services for saving and validating Vetmanager account connections."""

from __future__ import annotations

import asyncio
import time

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from exceptions import AuthError, HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_resolver import resolve_vetmanager_host as _resolve_host_via_billing
from observability_logging import RUNTIME_LOGGER
from service_metrics import record_upstream_failure, record_upstream_request
from domain_validation import validate_domain as _validate_domain
from storage_models import CONNECTION_STATUS_ACTIVE, CONNECTION_STATUS_DISABLED, VetmanagerConnection
from vetmanager_auth import (
    VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
    VETMANAGER_AUTH_MODE_USER_TOKEN,
    resolve_vetmanager_credentials,
)
from vm_transport.pool import get_shared_http_client
from vm_transport.retry import RETRY_STATUS_CODES, backoff_seconds, parse_retry_after

REQUEST_TIMEOUT = 30.0

INTEGRATION_HEALTH_ACTIVE = "active"
INTEGRATION_HEALTH_INVALID = "invalid"
INTEGRATION_HEALTH_REAUTH_REQUIRED = "reauth_required"
INTEGRATION_HEALTH_UNKNOWN = "unknown"
TOKEN_AUTH_APP_NAME = "vetmanager-mcp"
_PROBE_TARGET = "vetmanager_api_probe"
_TOKEN_AUTH_TARGET = "vetmanager_token_auth"
_ACCOUNT_SAVE_LOCKS: dict[int, asyncio.Lock] = {}
_ACCOUNT_SAVE_LOCKS_GUARD: asyncio.Lock | None = None
_ACCOUNT_LOGIN_PREPARE_TASKS: dict[int, asyncio.Task[tuple[str, str]]] = {}
_ACCOUNT_LOGIN_PREPARE_GUARD: asyncio.Lock | None = None


def _lock_bound_to_other_loop(lock: asyncio.Lock | None) -> bool:
    if lock is None:
        return False
    try:
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        return False
    bound_loop = getattr(lock, "_loop", None)
    return bound_loop is not None and bound_loop is not running_loop


def _get_account_save_locks_guard() -> asyncio.Lock:
    global _ACCOUNT_SAVE_LOCKS_GUARD
    if _ACCOUNT_SAVE_LOCKS_GUARD is None or _lock_bound_to_other_loop(_ACCOUNT_SAVE_LOCKS_GUARD):
        _ACCOUNT_SAVE_LOCKS_GUARD = asyncio.Lock()
    return _ACCOUNT_SAVE_LOCKS_GUARD


async def _get_account_save_lock(account_id: int) -> asyncio.Lock:
    lock = _ACCOUNT_SAVE_LOCKS.get(account_id)
    if _lock_bound_to_other_loop(lock):
        lock = asyncio.Lock()
        _ACCOUNT_SAVE_LOCKS[account_id] = lock
    if lock is not None:
        return lock
    async with _get_account_save_locks_guard():
        lock = _ACCOUNT_SAVE_LOCKS.get(account_id)
        if _lock_bound_to_other_loop(lock):
            lock = asyncio.Lock()
            _ACCOUNT_SAVE_LOCKS[account_id] = lock
        if lock is None:
            lock = asyncio.Lock()
            _ACCOUNT_SAVE_LOCKS[account_id] = lock
        return lock


def _get_account_login_prepare_guard() -> asyncio.Lock:
    global _ACCOUNT_LOGIN_PREPARE_GUARD
    if _ACCOUNT_LOGIN_PREPARE_GUARD is None or _lock_bound_to_other_loop(_ACCOUNT_LOGIN_PREPARE_GUARD):
        _ACCOUNT_LOGIN_PREPARE_GUARD = asyncio.Lock()
    return _ACCOUNT_LOGIN_PREPARE_GUARD


async def _run_login_prepare_once(
    account_id: int,
    factory,
) -> tuple[str, str]:
    owner = False
    async with _get_account_login_prepare_guard():
        task = _ACCOUNT_LOGIN_PREPARE_TASKS.get(account_id)
        if task is None:
            task = asyncio.create_task(factory())
            _ACCOUNT_LOGIN_PREPARE_TASKS[account_id] = task
            owner = True
    try:
        return await task
    finally:
        if owner:
            async with _get_account_login_prepare_guard():
                if _ACCOUNT_LOGIN_PREPARE_TASKS.get(account_id) is task:
                    _ACCOUNT_LOGIN_PREPARE_TASKS.pop(account_id, None)


def _record_upstream_attempt(*, target: str, ok: bool, reason: str | None = None, duration_seconds: float) -> None:
    status = "success" if ok else "error"
    record_upstream_request(
        target=target,
        status=status,
        duration_seconds=duration_seconds,
    )
    if not ok and reason:
        record_upstream_failure(target=target, reason=reason)


async def _request_with_retry(
    method: str,
    url: str,
    *,
    target: str,
    headers: dict[str, str],
    params: dict | None = None,
    files: dict | None = None,
    account_connection_id: int | None = None,
    timeout_message: str,
    unavailable_message: str,
) -> httpx.Response:
    client = await get_shared_http_client()
    max_attempts = 3

    for attempt in range(max_attempts):
        started = time.monotonic()
        try:
            if method == "GET":
                response = await client.get(url, params=params, headers=headers)
            elif method == "POST":
                response = await client.post(url, headers=headers, files=files)
            else:
                raise RuntimeError(f"unsupported method {method}")
        except httpx.ConnectTimeout as exc:
            elapsed = time.monotonic() - started
            _record_upstream_attempt(
                target=target,
                ok=False,
                reason="connect_timeout",
                duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Vetmanager auth probe timed out while connecting",
                extra={
                    "event_name": "vetmanager_auth_probe_retry",
                    "target": target,
                    "error_class": type(exc).__name__,
                    "attempt": attempt + 1,
                    "account_connection_id": account_connection_id,
                },
            )
            if attempt + 1 < max_attempts:
                await asyncio.sleep(backoff_seconds(attempt))
                continue
            raise VetmanagerTimeoutError(timeout_message) from exc
        except httpx.TimeoutException as exc:
            elapsed = time.monotonic() - started
            _record_upstream_attempt(
                target=target,
                ok=False,
                reason="timeout",
                duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Vetmanager auth probe timed out",
                extra={
                    "event_name": "vetmanager_auth_probe_failed",
                    "target": target,
                    "error_class": type(exc).__name__,
                    "account_connection_id": account_connection_id,
                },
            )
            raise VetmanagerTimeoutError(timeout_message) from exc
        except httpx.RequestError as exc:
            elapsed = time.monotonic() - started
            _record_upstream_attempt(
                target=target,
                ok=False,
                reason="request_error",
                duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Vetmanager auth probe request error",
                extra={
                    "event_name": "vetmanager_auth_probe_failed",
                    "target": target,
                    "error_class": type(exc).__name__,
                    "account_connection_id": account_connection_id,
                },
            )
            raise VetmanagerError(unavailable_message) from exc

        elapsed = time.monotonic() - started
        if response.status_code in RETRY_STATUS_CODES - {429}:
            _record_upstream_attempt(
                target=target,
                ok=False,
                reason=f"http_{response.status_code}",
                duration_seconds=elapsed,
            )
            RUNTIME_LOGGER.warning(
                "Vetmanager auth probe received retryable upstream status",
                extra={
                    "event_name": "vetmanager_auth_probe_retry",
                    "target": target,
                    "status_code": response.status_code,
                    "attempt": attempt + 1,
                    "account_connection_id": account_connection_id,
                },
            )
            if attempt + 1 < max_attempts:
                await asyncio.sleep(
                    backoff_seconds(
                        attempt,
                        parse_retry_after(response.headers.get("Retry-After")),
                    )
                )
                continue
        _record_upstream_attempt(
            target=target,
            ok=response.status_code < 400,
            reason=None if response.status_code < 400 else f"http_{response.status_code}",
            duration_seconds=elapsed,
        )
        if response.status_code < 400:
            RUNTIME_LOGGER.info(
                "Vetmanager auth probe succeeded",
                extra={
                    "event_name": "vetmanager_auth_probe_succeeded",
                    "target": target,
                    "status_code": response.status_code,
                    "account_connection_id": account_connection_id,
                },
            )
        else:
            RUNTIME_LOGGER.warning(
                "Vetmanager auth probe failed",
                extra={
                    "event_name": "vetmanager_auth_probe_failed",
                    "target": target,
                    "status_code": response.status_code,
                    "account_connection_id": account_connection_id,
                },
            )
        return response

    raise RuntimeError("unreachable")


async def resolve_vetmanager_host(domain: str) -> str:
    """Resolve normalized clinic domain into an allowlisted HTTPS host."""
    normalized_domain = _validate_domain(domain.strip())
    return await _resolve_host_via_billing(normalized_domain, max_retries=0)


async def validate_domain_api_key_connection(
    domain: str,
    api_key: str,
    *,
    resolved_host: str | None = None,
    account_connection_id: int | None = None,
) -> str:
    """Validate domain+api_key pair and return resolved Vetmanager host."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_api_key = api_key.strip()
    if not normalized_api_key:
        raise AuthError("Invalid Vetmanager API key.", status_code=401)

    resolved_host = resolved_host or await resolve_vetmanager_host(normalized_domain)
    probe = await _request_with_retry(
        "GET",
        f"{resolved_host}/rest/api/client",
        target=_PROBE_TARGET,
        params={"limit": 1, "offset": 0},
        headers={
            "X-REST-API-KEY": normalized_api_key,
            "Accept": "application/json",
        },
        account_connection_id=account_connection_id,
        timeout_message="Vetmanager connection test timed out.",
        unavailable_message="Vetmanager connection test is temporarily unavailable.",
    )

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
    account_connection_id: int | None = None,
) -> tuple[str, str]:
    """Exchange login/password into a Vetmanager user token."""
    normalized_domain = _validate_domain(domain.strip())
    normalized_login = login.strip()
    if not normalized_login or not password:
        raise AuthError("Invalid Vetmanager login or password.", status_code=401)

    resolved_host = await resolve_vetmanager_host(normalized_domain)
    response = await _request_with_retry(
        "POST",
        f"{resolved_host}/token_auth.php",
        target=_TOKEN_AUTH_TARGET,
        headers={
            "Accept": "application/json",
        },
        files={
            "login": (None, normalized_login),
            "password": (None, password),
            "app_name": (None, TOKEN_AUTH_APP_NAME),
        },
        account_connection_id=account_connection_id,
        timeout_message="Vetmanager authorization timed out.",
        unavailable_message="Vetmanager authorization is temporarily unavailable.",
    )

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
    account_connection_id: int | None = None,
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
    probe = await _request_with_retry(
        "GET",
        f"{resolved_host}/rest/api/user",
        target=_PROBE_TARGET,
        params={"limit": 1, "offset": 0},
        headers={
            "X-USER-TOKEN": normalized_user_token,
            "X-APP-NAME": normalized_app_name,
            "Accept": "application/json",
        },
        account_connection_id=account_connection_id,
        timeout_message="Vetmanager user-token validation timed out.",
        unavailable_message="Vetmanager user-token validation is temporarily unavailable.",
    )

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
            ).with_for_update()
        )
    ).scalars().all()
    for existing in existing_connections:
        existing.status = CONNECTION_STATUS_DISABLED


async def _find_matching_active_connection(
    session: AsyncSession,
    *,
    account_id: int,
    auth_mode: str,
    domain: str,
    expected_credentials: dict[str, str],
    encryption_key: str | None,
) -> VetmanagerConnection | None:
    if encryption_key is None:
        return None
    rows = (
        await session.execute(
            select(VetmanagerConnection).where(
                VetmanagerConnection.account_id == account_id,
                VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE,
                VetmanagerConnection.auth_mode == auth_mode,
                VetmanagerConnection.domain == domain,
            ).with_for_update()
        )
    ).scalars().all()
    for row in rows:
        try:
            credentials = row.get_credentials(encryption_key=encryption_key)
        except Exception:
            continue
        if all(credentials.get(key) == value for key, value in expected_credentials.items()):
            return row
    return None


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
    lock = await _get_account_save_lock(account_id)
    async with lock:
        async with session.begin():
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
    lock = await _get_account_save_lock(account_id)
    async with lock:
        async with session.begin():
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

    async def _prepare_login_credentials() -> tuple[str, str]:
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
        return resolved_host, user_token

    _, user_token = await _run_login_prepare_once(account_id, _prepare_login_credentials)
    lock = await _get_account_save_lock(account_id)
    async with lock:
        async with session.begin():
            existing = await _find_matching_active_connection(
                session,
                account_id=account_id,
                auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
                domain=normalized_domain,
                expected_credentials={
                    "domain": normalized_domain,
                    "user_token": user_token,
                    "app_name": TOKEN_AUTH_APP_NAME,
                },
                encryption_key=encryption_key,
            )
            if existing is not None:
                connection = existing
            else:
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
            await validate_domain_api_key_connection(
                auth_context.domain,
                auth_context.credential,
                account_connection_id=connection.id,
            )
            return INTEGRATION_HEALTH_ACTIVE, "Integration is active."
        if auth_context.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN:
            await validate_user_token_connection(
                auth_context.domain,
                auth_context.credential,
                app_name=auth_context.app_name or TOKEN_AUTH_APP_NAME,
                account_connection_id=connection.id,
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
        RUNTIME_LOGGER.warning(
            "Vetmanager connection health probe failed",
            extra={
                "event_name": "connection_health_failed",
                "account_connection_id": connection.id,
                "auth_mode": auth_context.auth_mode,
                "error_class": "upstream_probe_error",
            },
        )
        return (
            INTEGRATION_HEALTH_UNKNOWN,
            "Integration health could not be verified right now. Try again later.",
        )
    return INTEGRATION_HEALTH_UNKNOWN, "Integration health could not be determined."
