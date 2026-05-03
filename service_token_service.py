"""Services for issuing bearer tokens from account context."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain_validation import validate_ip_mask
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_audit import (
    TOKEN_EVENT_CREATED,
    TOKEN_EVENT_REVOKED,
    add_token_usage_log,
    commit_token_usage_log,
)
from bearer_token_manager import generate_bearer_token
from observability_logging import RUNTIME_LOGGER
from storage_models import ServiceBearerToken
from tool_access_registry import PRESET_FULL_ACCESS, get_token_preset_scopes, normalize_token_preset

WILDCARD_IP_MASK = "*.*.*.*"


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
    ip_mask: str,
    expires_in_days: int | None = None,
    is_depersonalized: bool = False,
    access_preset: str = PRESET_FULL_ACCESS,
) -> tuple[ServiceBearerToken, str]:
    """Create a new bearer token record and return it with the raw one-time value.

    Stage 155: ip_mask is required (no default). Wildcard ('*.*.*.*') is
    persisted as the literal string — there is no implicit "NULL means
    unrestricted" fallback. Caller (web layer) is responsible for collecting
    explicit user confirmation before submitting wildcard.
    """
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("Token name is required.")
    if len(normalized_name) > 128:
        raise ValueError("Token name must be 128 characters or fewer.")
    if expires_in_days is not None and expires_in_days <= 0:
        raise ValueError("Token expiry must be a positive number of days.")

    effective_ip_mask = validate_ip_mask(ip_mask)
    normalized_preset = normalize_token_preset(access_preset)

    raw_token = generate_bearer_token()
    expires_at = None
    if expires_in_days is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    token = ServiceBearerToken(
        account_id=account_id,
        name=normalized_name,
        status="active",
        is_depersonalized=is_depersonalized,
        expires_at=expires_at,
        allowed_ip_mask=effective_ip_mask,
    )
    token.set_raw_token(raw_token)
    token.set_scopes(get_token_preset_scopes(normalized_preset))
    session.add(token)
    await session.flush()
    audit_event = add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=TOKEN_EVENT_CREATED,
        details={
            "name": token.name,
            "token_prefix": token.token_prefix,
            "expires_at": _token_expiry_string(token.expires_at),
            "ip_mask": token.allowed_ip_mask,
            "is_depersonalized": token.is_depersonalized,
            "access_preset": normalized_preset,
        },
    )
    await commit_token_usage_log(session, audit_event)
    await session.refresh(token)
    if effective_ip_mask == WILDCARD_IP_MASK:
        # Stage 155: operator-visible signal that an unrestricted token was
        # issued (web UX requires explicit confirm checkbox; this log makes
        # the event traceable in centralized logs without parsing the audit DB).
        RUNTIME_LOGGER.warning(
            "token_created_with_wildcard_ip",
            extra={
                "event_name": "token_created_with_wildcard_ip",
                "account_id": account_id,
                "token_id": token.id,
                "token_name": token.name,
            },
        )
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
    audit_event = add_token_usage_log(
        session,
        bearer_token_id=token.id,
        event_type=TOKEN_EVENT_REVOKED,
        details={
            "name": token.name,
            "token_prefix": token.token_prefix,
            "revoked_at": _token_expiry_string(effective_revoked_at),
        },
    )
    await commit_token_usage_log(session, audit_event)
    await session.refresh(token)
    return token
