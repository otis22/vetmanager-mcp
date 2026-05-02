"""Cleanup helpers for expired bearer tokens."""

from __future__ import annotations

from datetime import datetime, timezone
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth_audit import (
    TOKEN_EVENT_EXPIRED,
    TOKEN_EVENT_EXPIRY_WARNING_1,
    TOKEN_EVENT_EXPIRY_WARNING_7,
    TOKEN_EVENT_EXPIRY_WARNING_14,
    add_token_usage_log,
)
from observability_logging import RUNTIME_LOGGER
from service_metrics import record_business_event
from storage_models import ServiceBearerToken, TOKEN_STATUS_ACTIVE, TokenUsageLog


# Stage 154: ascending thresholds; selection rule emits min(crossed - emitted).
_EXPIRY_THRESHOLDS_DAYS = (1, 7, 14)
_EXPIRY_EVENT_BY_THRESHOLD = {
    1: TOKEN_EVENT_EXPIRY_WARNING_1,
    7: TOKEN_EVENT_EXPIRY_WARNING_7,
    14: TOKEN_EVENT_EXPIRY_WARNING_14,
}
_EXPIRY_WARNING_EVENT_TYPES = tuple(_EXPIRY_EVENT_BY_THRESHOLD.values())


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


def _normalize_to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _emitted_thresholds_for_token(
    session: AsyncSession, *, bearer_token_id: int,
) -> set[int]:
    rows = (
        await session.execute(
            select(TokenUsageLog.event_type)
            .where(TokenUsageLog.bearer_token_id == bearer_token_id)
            .where(TokenUsageLog.event_type.in_(_EXPIRY_WARNING_EVENT_TYPES))
        )
    ).scalars().all()
    return {n for n, et in _EXPIRY_EVENT_BY_THRESHOLD.items() if et in set(rows)}


async def scan_token_expiry_warnings(
    session: AsyncSession,
    *,
    account_id: int | None = None,
    now: datetime | None = None,
) -> int:
    """Stage 154: emit pre-expiry warnings (one per (token, threshold) min crossed).

    For each active token with `expires_at > now`, compute `days_to_expiry = ceil(...)`,
    pick `min(crossed - already_emitted)` threshold from (1, 7, 14), persist a
    `token_usage_logs` row with that distinct event_type, increment per-threshold
    business event counter, and structured-log the warning.

    Returns the number of warnings emitted in this call.
    """
    current = _normalize_to_utc(now or datetime.now(timezone.utc))

    query = (
        select(ServiceBearerToken)
        .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
        .where(ServiceBearerToken.expires_at.is_not(None))
        .where(ServiceBearerToken.expires_at > current)
    )
    if account_id is not None:
        query = query.where(ServiceBearerToken.account_id == account_id)

    tokens = (await session.execute(query)).scalars().all()
    emitted_count = 0
    emit_records: list[tuple[int, int, int, int, str]] = []

    for token in tokens:
        expires_at_utc = _normalize_to_utc(token.expires_at)
        delta_seconds = (expires_at_utc - current).total_seconds()
        if delta_seconds <= 0:
            continue
        # delta_seconds > 0 guarantees ceil(delta/86400) >= 1, so days_to_expiry >= 1.
        days_to_expiry = ceil(delta_seconds / 86400)
        crossed = {n for n in _EXPIRY_THRESHOLDS_DAYS if days_to_expiry <= n}
        if not crossed:
            continue
        # N+1 dedup query — acceptable at current scale (≤ ~30 active tokens
        # per account). Switch to batched `IN (token_ids)` lookup if cardinality
        # grows materially.
        already = await _emitted_thresholds_for_token(session, bearer_token_id=token.id)
        todo = crossed - already
        if not todo:
            continue
        threshold = min(todo)
        event_type = _EXPIRY_EVENT_BY_THRESHOLD[threshold]
        add_token_usage_log(
            session,
            bearer_token_id=token.id,
            event_type=event_type,
            details={
                "account_id": token.account_id,
                "token_prefix": token.token_prefix,
                "threshold_days": threshold,
                "days_to_expiry": days_to_expiry,
                "expires_at_utc": expires_at_utc.isoformat(),
            },
        )
        emit_records.append((token.id, token.account_id, threshold, days_to_expiry, event_type))
        emitted_count += 1

    if emitted_count == 0:
        return 0

    await session.commit()

    # Best-effort observability AFTER successful commit (per S3 source-of-truth contract).
    for token_id, acct_id, threshold, days, event_type in emit_records:
        record_business_event(event_type)
        RUNTIME_LOGGER.warning(
            "token_expiry_warning",
            extra={
                "event_name": "token_expiry_warning",
                "account_id": acct_id,
                "bearer_token_id": token_id,
                "threshold_days": threshold,
                "days_to_expiry": days,
            },
        )

    return emitted_count
