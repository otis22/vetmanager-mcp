"""Services for issuing bearer tokens from account context."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_audit import (
    TOKEN_EVENT_CREATED,
    TOKEN_EVENT_REVOKED,
    add_token_usage_log,
)
from bearer_token_manager import generate_bearer_token
from storage_models import ServiceBearerToken
from token_scopes import SUPPORTED_TOKEN_SCOPES


def _token_expiry_string(expires_at: datetime | None) -> str | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at.astimezone(timezone.utc).isoformat()

async def issue_service_bearer_token(
    session: AsyncSession,
    *,
    account_id: int,
    name: str,
    expires_in_days: int | None = None,
) -> tuple[ServiceBearerToken, str]:
    """Create a new bearer token record and return it with the raw one-time value."""
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Token name is required.")
    if len(normalized_name) > 128:
        raise ValueError("Token name must be 128 characters or fewer.")
    if expires_in_days is not None and expires_in_days <= 0:
        raise ValueError("Token expiry must be a positive number of days.")

    raw_token = generate_bearer_token()
    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    token = ServiceBearerToken(
        account_id=account_id,
        name=normalized_name,
        status="active",
        expires_at=expires_at,
    )
    token.set_raw_token(raw_token)
    token.set_scopes(SUPPORTED_TOKEN_SCOPES)
    session.add(token)
    await session.flush()
    add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=TOKEN_EVENT_CREATED,
        details={
            "name": token.name,
            "token_prefix": token.token_prefix,
            "expires_at": _token_expiry_string(token.expires_at),
        },
    )
    await session.commit()
    await session.refresh(token)
    return token, raw_token


async def revoke_service_bearer_token(
    session: AsyncSession,
    *,
    account_id: int,
    token_id: int,
    revoked_at: datetime | None = None,
) -> ServiceBearerToken:
    """Revoke one token owned by account and append a safe audit event."""
    token = await session.scalar(
        select(ServiceBearerToken).where(
            ServiceBearerToken.id == token_id,
            ServiceBearerToken.account_id == account_id,
        )
    )
    if token is None:
        raise ValueError("Bearer token not found.")
    if token.is_revoked():
        raise ValueError("Bearer token already revoked.")

    effective_revoked_at = revoked_at or datetime.now(timezone.utc)
    token.revoke(revoked_at=effective_revoked_at)
    add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=TOKEN_EVENT_REVOKED,
        details={
            "name": token.name,
            "token_prefix": token.token_prefix,
            "revoked_at": _token_expiry_string(effective_revoked_at),
        },
    )
    await session.commit()
    await session.refresh(token)
    return token
