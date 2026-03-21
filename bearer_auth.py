"""Bearer token lookup and account auth context resolution."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import bearer_rate_limiter
from bearer_token_manager import hash_bearer_token
from exceptions import AuthError
from storage_models import (
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_DISABLED,
    TokenUsageStat,
    VetmanagerConnection,
)
from vetmanager_auth import resolve_vetmanager_credentials


@dataclass(slots=True)
class BearerAuthContext:
    """Resolved runtime auth context for one bearer-authenticated request."""

    account_id: int
    bearer_token_id: int
    connection_id: int
    auth_mode: str
    domain: str
    api_key: str


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
        raise AuthError("Invalid bearer token.", status_code=401)

    token, account = token_row
    if token.is_revoked():
        raise AuthError("Revoked bearer token.", status_code=401)
    if token.is_expired(now=now):
        token.sync_status(now=now)
        raise AuthError("Expired bearer token.", status_code=401)
    if token.status == TOKEN_STATUS_DISABLED or account.status != "active":
        raise AuthError("Invalid bearer token.", status_code=401)
    await bearer_rate_limiter.BEARER_RATE_LIMITER.check_or_raise(token.id, now=now)

    connection_result = await session.execute(
        select(VetmanagerConnection)
        .where(VetmanagerConnection.account_id == account.id)
        .where(VetmanagerConnection.status == "active")
        .order_by(VetmanagerConnection.id.asc())
        .limit(1)
    )
    connection = connection_result.scalar_one_or_none()
    if connection is None:
        raise AuthError("Account connection not configured.", status_code=401)

    resolved = resolve_vetmanager_credentials(
        connection,
        encryption_key=encryption_key,
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
    )
