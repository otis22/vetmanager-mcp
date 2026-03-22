"""Bearer token lookup and account auth context resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bearer_rate_limiter
from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
    add_token_usage_log,
)
from bearer_token_manager import hash_bearer_token
from exceptions import AuthError, RateLimitError
from service_metrics import record_auth_failure
from storage_models import (
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_DISABLED,
    TokenUsageStat,
    VetmanagerConnection,
)
from vetmanager_auth import VetmanagerAuthContext, resolve_vetmanager_credentials


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
        raise AuthError("Invalid bearer token.", status_code=401)

    token, account = token_row
    if token.is_revoked():
        record_auth_failure(source="bearer_runtime", reason="revoked")
        add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_FAILED_REVOKED,
            details=_base_auth_details(
                account_id=account.id,
                token=token,
                reason="revoked",
            ),
        )
        await session.commit()
        raise AuthError("Revoked bearer token.", status_code=401)
    if token.is_expired(now=now):
        record_auth_failure(source="bearer_runtime", reason="expired")
        token.sync_status(now=now)
        add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_FAILED_EXPIRED,
            details=_base_auth_details(
                account_id=account.id,
                token=token,
                reason="expired",
            ),
        )
        await session.commit()
        raise AuthError("Expired bearer token.", status_code=401)
    if token.status == TOKEN_STATUS_DISABLED or account.status != "active":
        record_auth_failure(source="bearer_runtime", reason="disabled")
        raise AuthError("Invalid bearer token.", status_code=401)
    try:
        await bearer_rate_limiter.BEARER_RATE_LIMITER.check_or_raise(token.id, now=now)
    except RateLimitError as exc:
        record_auth_failure(source="bearer_runtime", reason="rate_limited")
        add_token_usage_log(
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
        await session.commit()
        raise

    connection_result = await session.execute(
        select(VetmanagerConnection)
        .where(VetmanagerConnection.account_id == account.id)
        .where(VetmanagerConnection.status == "active")
        .order_by(VetmanagerConnection.id.asc())
        .limit(1)
    )
    connection = connection_result.scalar_one_or_none()
    if connection is None:
        record_auth_failure(source="bearer_runtime", reason="no_connection")
        add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
            details=_base_auth_details(
                account_id=account.id,
                token=token,
                reason="no_connection",
            ),
        )
        await session.commit()
        raise AuthError("Account connection not configured.", status_code=401)

    resolved = resolve_vetmanager_credentials(
        connection,
        encryption_key=encryption_key,
    )
    add_token_usage_log(
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
    await session.commit()
    await session.refresh(token)
    return BearerAuthContext(
        account_id=account.id,
        bearer_token_id=token.id,
        connection_id=connection.id,
        auth_mode=resolved.auth_mode,
        domain=resolved.domain,
        api_key=resolved.api_key,
        vetmanager_auth=resolved,
        scopes=tuple(token.get_scopes()),
    )
