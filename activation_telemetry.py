"""Account activation telemetry for no-traffic detection."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from observability_logging import RUNTIME_LOGGER
from service_metrics import set_account_last_request_age_hours
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    CONNECTION_STATUS_ACTIVE,
    TOKEN_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    VetmanagerConnection,
)

SILENCE_THRESHOLDS_HOURS = (24, 72)

_ALERTED_THRESHOLDS: set[tuple[int, int]] = set()


def reset_activation_telemetry_state() -> None:
    """Clear process-local no-traffic warning dedup state for tests."""
    _ALERTED_THRESHOLDS.clear()


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _hours_between(now: datetime, then: datetime) -> float:
    return max(0.0, (_ensure_aware_utc(now) - _ensure_aware_utc(then)).total_seconds() / 3600)


def _iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _ensure_aware_utc(value).isoformat()


def _clear_account_dedup(account_id: int) -> None:
    _ALERTED_THRESHOLDS.difference_update({
        key for key in _ALERTED_THRESHOLDS if key[0] == account_id
    })


async def scan_activation_telemetry(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Refresh account activation gauges and emit best-effort silence warnings."""
    current = now or datetime.now(timezone.utc)
    stmt = (
        select(
            Account.id.label("account_id"),
            func.max(ServiceBearerToken.last_used_at).label("last_request_at"),
            func.min(ServiceBearerToken.created_at).label("earliest_token_created_at"),
            func.count(distinct(ServiceBearerToken.id)).label("live_token_count"),
        )
        .select_from(Account)
        .join(
            ServiceBearerToken,
            ServiceBearerToken.account_id == Account.id,
        )
        .where(Account.status == ACCOUNT_STATUS_ACTIVE)
        .where(
            exists()
            .where(VetmanagerConnection.account_id == Account.id)
            .where(VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE)
        )
        .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
        .where(
            or_(
                ServiceBearerToken.expires_at.is_(None),
                ServiceBearerToken.expires_at > current,
            )
        )
        .group_by(Account.id)
    )
    rows = (await session.execute(stmt)).all()

    gauges: dict[int, float] = {}
    live_account_ids: set[int] = set()
    emitted = 0
    for row in rows:
        account_id = int(row.account_id)
        live_account_ids.add(account_id)
        last_request_at = row.last_request_at
        earliest_token_created_at = row.earliest_token_created_at
        anchor_at = last_request_at or earliest_token_created_at
        if anchor_at is None:
            continue

        age_hours = _hours_between(current, anchor_at)
        gauges[account_id] = age_hours

        if age_hours < SILENCE_THRESHOLDS_HOURS[0]:
            _clear_account_dedup(account_id)
            continue

        ever_used = last_request_at is not None
        age_anchor = "last_request_at" if ever_used else "token_created_at"
        for threshold_hours in SILENCE_THRESHOLDS_HOURS:
            if age_hours < threshold_hours:
                continue
            dedup_key = (account_id, threshold_hours)
            if dedup_key in _ALERTED_THRESHOLDS:
                continue
            _ALERTED_THRESHOLDS.add(dedup_key)
            emitted += 1
            RUNTIME_LOGGER.warning(
                "Account traffic is silent.",
                extra={
                    "event_name": "account_traffic_silent",
                    "account_id": account_id,
                    "threshold_hours": threshold_hours,
                    "age_hours": age_hours,
                    "last_request_at_utc": _iso_or_none(last_request_at),
                    "ever_used": ever_used,
                    "age_anchor": age_anchor,
                    "live_token_count": int(row.live_token_count or 0),
                },
            )

    for account_id, _threshold in list(_ALERTED_THRESHOLDS):
        if account_id not in live_account_ids:
            _clear_account_dedup(account_id)
    set_account_last_request_age_hours(gauges)
    return emitted
