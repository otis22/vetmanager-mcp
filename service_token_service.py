"""Services for issuing bearer tokens from account context."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from bearer_token_manager import generate_bearer_token
from storage_models import ServiceBearerToken


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
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token, raw_token
