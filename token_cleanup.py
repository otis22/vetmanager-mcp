"""Cleanup helpers for expired bearer tokens."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_audit import TOKEN_EVENT_EXPIRED, add_token_usage_log
from storage_models import ServiceBearerToken, TOKEN_STATUS_ACTIVE


async def sync_expired_tokens(
    session: AsyncSession,
    *,
    account_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Mark expired active tokens as terminally expired and log the transition once."""
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)

    query = select(ServiceBearerToken).where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
    if account_id is not None:
        query = query.where(ServiceBearerToken.account_id == account_id)

    tokens = (await session.execute(query)).scalars().all()
    updated = 0
    for token in tokens:
        if token.sync_status(now=current) != "expired":
            continue
        add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=TOKEN_EVENT_EXPIRED,
            details={
                "account_id": token.account_id,
                "token_prefix": token.token_prefix,
                "reason": "expired_cleanup",
            },
        )
        updated += 1

    if updated:
        await session.commit()
    return updated
