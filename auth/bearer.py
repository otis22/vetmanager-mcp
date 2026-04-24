"""Bearer token lookup and account auth context resolution.

Stage 103a: lives in the `auth` package. The top-level `bearer_auth`
module remains as a shim that re-exports every name here for BC so
existing imports and test monkey-patches keep working.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from auth import rate_limit
from sqlalchemy import insert, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auth.context import VetmanagerAuthContext
from auth.vetmanager import resolve_vetmanager_credentials
from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_DISABLED,
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
    TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
    add_token_usage_log,
    commit_token_usage_log,
    get_request_audit_metadata,
)
from bearer_token_manager import hash_bearer_token
from domain_validation import ip_matches_mask
from exceptions import AuthError, RateLimitError
from observability_logging import RUNTIME_LOGGER, SECURITY_LOGGER
from request_context import get_current_request_context
from service_metrics import record_auth_failure
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_DISABLED,
    TokenUsageStat,
    VetmanagerConnection,
)


def _token_usage_stat_insert_statement(token_id: int):
    values = {"bearer_token_id": token_id, "request_count": 0}
    return insert(TokenUsageStat).values(**values)


def _token_usage_stat_conflict_insert_statement(dialect_name: str, token_id: int):
    values = {"bearer_token_id": token_id, "request_count": 0}
    if dialect_name == "sqlite":
        return sqlite_insert(TokenUsageStat).values(**values).on_conflict_do_nothing(
            index_elements=["bearer_token_id"]
        )
    if dialect_name == "postgresql":
        return postgresql_insert(TokenUsageStat).values(**values).on_conflict_do_nothing(
            index_elements=["bearer_token_id"]
        )
    return _token_usage_stat_insert_statement(token_id)


async def _increment_token_usage_stats(
    session: AsyncSession,
    *,
    token_id: int,
    used_at: datetime,
) -> None:
    try:
        dialect_name = session.get_bind().dialect.name
        async with session.begin_nested():
            await session.execute(
                _token_usage_stat_conflict_insert_statement(dialect_name, token_id)
            )
            await session.execute(
                update(TokenUsageStat)
                .where(TokenUsageStat.bearer_token_id == token_id)
                .values(
                    request_count=TokenUsageStat.request_count + 1,
                    last_used_at=used_at,
                )
            )
    except Exception as exc:
        RUNTIME_LOGGER.warning(
            "Token usage stats update failed; continuing auth success.",
            extra={
                "event_name": "token_usage_stats_update_failed",
                "token_id": token_id,
                "error_class": exc.__class__.__name__,
            },
        )


@dataclass(slots=True)
class BearerAuthContext:
    """Resolved runtime auth context for one bearer-authenticated request."""

    account_id: int
    bearer_token_id: int
    connection_id: int
    auth_mode: str
    domain: str
    api_key: str
    vetmanager_auth: VetmanagerAuthContext
    scopes: tuple[str, ...]
    is_depersonalized: bool


def _base_auth_details(
    *,
    account_id: int,
    token: ServiceBearerToken,
    reason: str | None = None,
    connection: VetmanagerConnection | None = None,
    auth_mode: str | None = None,
    domain: str | None = None,
    retry_after_seconds: int | None = None,
) -> dict[str, str | int | None]:
    details: dict[str, str | int | None] = {
        "account_id": account_id,
        "token_prefix": token.token_prefix,
        "reason": reason,
        "connection_id": connection.id if connection is not None else None,
        "auth_mode": auth_mode,
        "domain": domain,
        "retry_after_seconds": retry_after_seconds,
    }
    return details


def _security_log_extra(*, source: str, reason: str) -> dict[str, str]:
    client_ip, _ = get_request_audit_metadata()
    context = get_current_request_context()
    extra = {
        "event_name": "bearer_auth_failed",
        "source": source,
        "reason": reason,
    }
    if client_ip is not None:
        extra["client_ip"] = client_ip
    for key in ("request_id", "correlation_id"):
        if value := context.get(key):
            extra[key] = value
    return extra


def _log_bearer_runtime_failure(reason: str) -> None:
    SECURITY_LOGGER.warning(
        "Bearer runtime authorization rejected.",
        extra=_security_log_extra(source="bearer_runtime", reason=reason),
    )


async def _reject(
    session: AsyncSession,
    *,
    token: ServiceBearerToken,
    account: Account,
    metric_reason: str,
    log_event: str,
    log_reason: str,
    message: str,
    status_code: int,
    retry_after_seconds: int | None = None,
    audit_best_effort: bool = False,
) -> NoReturn:
    """Record failure metric + audit log + commit, then raise AuthError.

    Stage 103.1: consolidates the repeated reject-and-log pattern across
    every validation branch of `resolve_bearer_auth_context`. Each branch
    used to duplicate 8-10 lines of `record_auth_failure` / `add_token_usage_log`
    / `await session.commit()` / `raise AuthError(...)`. This helper makes
    the pipeline read as a linear sequence of checks with a single uniform
    failure path, reducing the surface for "forgot to commit the audit log"
    regressions.
    """
    record_auth_failure(source="bearer_runtime", reason=metric_reason)
    token_id = token.id
    audit_event = add_token_usage_log(
        session,
        bearer_token_id=token_id,
        event_type=log_event,
        details=_base_auth_details(
            account_id=account.id,
            token=token,
            reason=log_reason,
            retry_after_seconds=retry_after_seconds,
        ),
    )
    try:
        await commit_token_usage_log(session, audit_event)
    except Exception:
        if not audit_best_effort:
            raise
        try:
            await session.rollback()
        except Exception:
            pass
        SECURITY_LOGGER.warning(
            "Failed to persist token audit event.",
            extra={
                "event_name": "token_audit_log_failed",
                "token_event_type": log_event,
                "bearer_token_id": token_id,
                "reason": log_reason,
            },
            exc_info=True,
        )
    raise AuthError(message, status_code=status_code)


async def resolve_bearer_auth_context(
    raw_token: str,
    session: AsyncSession,
    *,
    encryption_key: str | None = None,
    now: datetime | None = None,
) -> BearerAuthContext:
    """Resolve bearer token into account and active Vetmanager connection."""
    token_hash = hash_bearer_token(raw_token)

    token_result = await session.execute(
        select(ServiceBearerToken, Account)
        .join(Account, Account.id == ServiceBearerToken.account_id)
        .where(ServiceBearerToken.token_hash == token_hash)
    )
    token_row = token_result.first()
    if token_row is None:
        record_auth_failure(source="bearer_runtime", reason="invalid_token")
        _log_bearer_runtime_failure("invalid_token")
        raise AuthError("Invalid authorization.", status_code=401)

    token, account = token_row
    if token.is_revoked():
        await _reject(
            session,
            token=token,
            account=account,
            metric_reason="revoked",
            log_event=TOKEN_EVENT_AUTH_FAILED_REVOKED,
            log_reason="revoked",
            message="Invalid authorization.",
            status_code=401,
        )
    if token.is_expired(now=now):
        token.sync_status(now=now)
        await _reject(
            session,
            token=token,
            account=account,
            metric_reason="expired",
            log_event=TOKEN_EVENT_AUTH_FAILED_EXPIRED,
            log_reason="expired",
            message="Invalid authorization.",
            status_code=401,
        )
    if token.status == TOKEN_STATUS_DISABLED or account.status != ACCOUNT_STATUS_ACTIVE:
        await _reject(
            session,
            token=token,
            account=account,
            metric_reason="disabled",
            log_event=TOKEN_EVENT_AUTH_FAILED_DISABLED,
            log_reason="disabled",
            message="Invalid authorization.",
            status_code=401,
            audit_best_effort=True,
        )

    # IP mask enforcement
    effective_mask = token.get_allowed_ip_mask()
    if effective_mask != "*.*.*.*":
        client_ip, _ = get_request_audit_metadata()
        if client_ip is None or not ip_matches_mask(client_ip, effective_mask):
            await _reject(
                session,
                token=token,
                account=account,
                metric_reason="ip_denied",
                log_event=TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
                log_reason="ip_denied",
                message="Invalid authorization.",
                status_code=403,
            )

    try:
        # Read the rate limiter through the `auth.rate_limit` module
        # (not via a `from ... import` that would snapshot the object at
        # import time) so `reset_bearer_rate_limiter()` — which rebinds
        # the module-level singleton — takes effect on subsequent calls.
        await rate_limit.BEARER_RATE_LIMITER.check_or_raise(token.id)
    except RateLimitError as exc:
        # Rate-limit branch re-raises RateLimitError (not AuthError), so it
        # has its own log+commit sequence rather than using _reject.
        record_auth_failure(source="bearer_runtime", reason="rate_limited")
        audit_event = add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_RATE_LIMITED,
            details=_base_auth_details(
                account_id=account.id,
                token=token,
                reason="rate_limited",
                retry_after_seconds=exc.retry_after_seconds,
            ),
        )
        await commit_token_usage_log(session, audit_event)
        raise

    scopes = tuple(token.get_scopes())
    if not scopes:
        await _reject(
            session,
            token=token,
            account=account,
            metric_reason="no_scopes",
            log_event=TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
            log_reason="no_scopes",
            message="Bearer token has no authorized scopes.",
            status_code=403,
        )

    connection_result = await session.execute(
        select(VetmanagerConnection)
        .where(VetmanagerConnection.account_id == account.id)
        .where(VetmanagerConnection.status == "active")
        .order_by(VetmanagerConnection.id.asc())
        .limit(1)
    )
    connection = connection_result.scalar_one_or_none()
    if connection is None:
        await _reject(
            session,
            token=token,
            account=account,
            metric_reason="no_connection",
            log_event=TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
            log_reason="no_connection",
            message="Invalid authorization.",
            status_code=401,
        )

    resolved = resolve_vetmanager_credentials(
        connection,
        encryption_key=encryption_key,
    )
    audit_event = add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
        details=_base_auth_details(
            account_id=account.id,
            token=token,
            reason="succeeded",
            connection=connection,
            auth_mode=resolved.auth_mode,
            domain=resolved.domain,
        ),
    )
    token.mark_used(used_at=now)
    await session.flush([token])
    await _increment_token_usage_stats(
        session,
        token_id=token.id,
        used_at=token.last_used_at,
    )
    await commit_token_usage_log(session, audit_event)
    await session.refresh(token)
    return BearerAuthContext(
        account_id=account.id,
        bearer_token_id=token.id,
        connection_id=connection.id,
        auth_mode=resolved.auth_mode,
        domain=resolved.domain,
        api_key=resolved.api_key,
        vetmanager_auth=resolved,
        scopes=scopes,
        is_depersonalized=token.is_depersonalized,
    )
