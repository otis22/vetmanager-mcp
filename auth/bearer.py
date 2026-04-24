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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth.context import VetmanagerAuthContext
from auth.vetmanager import resolve_vetmanager_credentials
from auth_audit import (
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
from service_metrics import record_auth_failure
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_DISABLED,
    TokenUsageStat,
    VetmanagerConnection,
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
    audit_event = add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=log_event,
        details=_base_auth_details(
            account_id=account.id,
            token=token,
            reason=log_reason,
            retry_after_seconds=retry_after_seconds,
        ),
    )
    await commit_token_usage_log(session, audit_event)
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
        # Disabled token / account — no audit log per existing contract
        # (validated by tests: only the metric counter increments).
        record_auth_failure(source="bearer_runtime", reason="disabled")
        raise AuthError("Invalid authorization.", status_code=401)

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
    usage_stats = await session.scalar(
        select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == token.id)
    )
    if usage_stats is None:
        usage_stats = TokenUsageStat(
            bearer_token_id=token.id,
            request_count=0,
        )
        session.add(usage_stats)
    usage_stats.request_count += 1
    usage_stats.last_used_at = token.last_used_at
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
