"""Account activation telemetry for no-traffic detection."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import distinct, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from activation_events import (
    cleanup_activation_events,
    is_activation_event_cleanup_due,
    mark_activation_event_cleanup_succeeded,
)
from observability_logging import RUNTIME_LOGGER
from service_metrics import (
    set_account_last_request_age_hours,
    set_activation_event_accounts,
    set_activation_funnel_accounts,
)
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    CONNECTION_STATUS_ACTIVE,
    TOKEN_STATUS_ACTIVE,
    Account,
    ActivationEvent,
    ServiceBearerToken,
    TokenUsageStat,
    VetmanagerConnection,
)

SILENCE_THRESHOLDS_HOURS = (24, 72)
ACTIVATION_SCAN_CACHE_TTL = timedelta(seconds=60)

_ALERTED_THRESHOLDS: set[tuple[int, int]] = set()
_ACTIVATION_SCAN_CACHE_AT: datetime | None = None
_ACTIVATION_SCAN_CACHE_FUNNEL: dict[str, int] | None = None
_ACTIVATION_SCAN_CACHE_EVENTS: dict[tuple[str, str, str, str], int] | None = None


def reset_activation_telemetry_state() -> None:
    """Clear process-local no-traffic warning dedup state for tests."""
    global _ACTIVATION_SCAN_CACHE_AT, _ACTIVATION_SCAN_CACHE_FUNNEL, _ACTIVATION_SCAN_CACHE_EVENTS
    _ALERTED_THRESHOLDS.clear()
    _ACTIVATION_SCAN_CACHE_AT = None
    _ACTIVATION_SCAN_CACHE_FUNNEL = None
    _ACTIVATION_SCAN_CACHE_EVENTS = None


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


def _apply_activation_scan_cache(current: datetime) -> bool:
    if (
        _ACTIVATION_SCAN_CACHE_AT is None
        or _ACTIVATION_SCAN_CACHE_FUNNEL is None
        or _ACTIVATION_SCAN_CACHE_EVENTS is None
    ):
        return False
    if current - _ACTIVATION_SCAN_CACHE_AT >= ACTIVATION_SCAN_CACHE_TTL:
        return False
    set_activation_funnel_accounts(dict(_ACTIVATION_SCAN_CACHE_FUNNEL))
    set_activation_event_accounts(dict(_ACTIVATION_SCAN_CACHE_EVENTS))
    return True


def _store_activation_scan_cache(
    current: datetime,
    funnel_values: dict[str, int],
    event_values: dict[tuple[str, str, str, str], int],
) -> None:
    global _ACTIVATION_SCAN_CACHE_AT, _ACTIVATION_SCAN_CACHE_FUNNEL, _ACTIVATION_SCAN_CACHE_EVENTS
    _ACTIVATION_SCAN_CACHE_AT = current
    _ACTIVATION_SCAN_CACHE_FUNNEL = dict(funnel_values)
    _ACTIVATION_SCAN_CACHE_EVENTS = dict(event_values)


async def scan_activation_telemetry(
    session: AsyncSession,
    *,
    now: datetime | None = None,
) -> int:
    """Refresh account activation gauges and emit best-effort silence warnings."""
    current = now or datetime.now(timezone.utc)
    try:
        cleanup_due = is_activation_event_cleanup_due(now=current)
        deleted_old_events = await cleanup_activation_events(session, now=current)
        if deleted_old_events:
            await session.commit()
        if cleanup_due:
            mark_activation_event_cleanup_succeeded(now=current)
    except Exception as exc:
        await session.rollback()
        RUNTIME_LOGGER.warning(
            "Activation event cleanup failed",
            extra={
                "event_name": "activation_event_cleanup_failed",
                "error_class": type(exc).__name__,
            },
        )

    if not _apply_activation_scan_cache(current):
        new_account_cutoff = current - timedelta(days=30)
        active_accounts_stmt = (
            select(Account.id)
            .where(Account.status == ACCOUNT_STATUS_ACTIVE)
            .where(Account.archived_at.is_(None))
        )
        account_ids = set((await session.execute(active_accounts_stmt)).scalars().all())
        connected_account_ids = set(
            (
                await session.execute(
                    select(VetmanagerConnection.account_id)
                    .join(Account, Account.id == VetmanagerConnection.account_id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE)
                )
            ).scalars().all()
        )
        active_token_account_ids = set(
            (
                await session.execute(
                    select(ServiceBearerToken.account_id)
                    .join(Account, Account.id == ServiceBearerToken.account_id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
                    .where(
                        or_(
                            ServiceBearerToken.expires_at.is_(None),
                            ServiceBearerToken.expires_at > current,
                        )
                    )
                )
            ).scalars().all()
        )
        recent_usage_cutoff = current - timedelta(days=7)
        recent_usage_account_ids = set(
            (
                await session.execute(
                    select(ServiceBearerToken.account_id)
                    .join(Account, Account.id == ServiceBearerToken.account_id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
                    .where(
                        or_(
                            ServiceBearerToken.expires_at.is_(None),
                            ServiceBearerToken.expires_at > current,
                        )
                    )
                    .where(ServiceBearerToken.last_used_at >= recent_usage_cutoff)
                )
            ).scalars().all()
        )
        connected_with_active_token_ids = connected_account_ids & active_token_account_ids
        connected_recent_usage_ids = connected_with_active_token_ids & recent_usage_account_ids
        new_account_ids = set(
            (
                await session.execute(
                    select(Account.id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(Account.created_at >= new_account_cutoff)
                )
            ).scalars().all()
        )
        integration_saved_ids = new_account_ids & connected_account_ids
        token_issued_ids = set(
            (
                await session.execute(
                    select(ServiceBearerToken.account_id)
                    .join(Account, Account.id == ServiceBearerToken.account_id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(Account.created_at >= new_account_cutoff)
                )
            ).scalars().all()
        )
        token_copied_ids = set(
            (
                await session.execute(
                    select(ActivationEvent.account_id)
                    .join(Account, Account.id == ActivationEvent.account_id)
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(Account.created_at >= new_account_cutoff)
                    .where(ActivationEvent.created_at >= new_account_cutoff)
                    .where(ActivationEvent.event_name == "token_copied")
                )
            ).scalars().all()
        )
        first_mcp_request_ids = set(
            (
                await session.execute(
                    select(ServiceBearerToken.account_id)
                    .join(Account, Account.id == ServiceBearerToken.account_id)
                    .outerjoin(
                        TokenUsageStat,
                        TokenUsageStat.bearer_token_id == ServiceBearerToken.id,
                    )
                    .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                    .where(Account.archived_at.is_(None))
                    .where(Account.created_at >= new_account_cutoff)
                    .where(
                        or_(
                            ServiceBearerToken.last_used_at.is_not(None),
                            TokenUsageStat.last_used_at.is_not(None),
                            TokenUsageStat.request_count > 0,
                        )
                    )
                )
            ).scalars().all()
        )
        funnel_values = {
            "registered": len(account_ids),
            "connected": len(connected_account_ids),
            "with_active_tokens": len(account_ids & active_token_account_ids),
            "ready_for_mcp": len(connected_with_active_token_ids),
            "with_recent_usage_7d": len(connected_recent_usage_ids),
            "new_registered": len(new_account_ids),
            "integration_saved": len(integration_saved_ids),
            "token_issued": len(new_account_ids & token_issued_ids),
            "token_copied": len(new_account_ids & token_copied_ids),
            "first_mcp_request": len(new_account_ids & first_mcp_request_ids),
        }
        set_activation_funnel_accounts(funnel_values)
        event_rows = (
            await session.execute(
                select(
                    ActivationEvent.event_name,
                    ActivationEvent.device_class,
                    ActivationEvent.auth_mode,
                    func.coalesce(ActivationEvent.reason_class, "none").label("reason"),
                    func.count(distinct(ActivationEvent.account_id)).label("account_count"),
                )
                .join(Account, Account.id == ActivationEvent.account_id)
                .where(Account.status == ACCOUNT_STATUS_ACTIVE)
                .where(Account.archived_at.is_(None))
                .where(Account.created_at >= new_account_cutoff)
                .where(ActivationEvent.created_at >= new_account_cutoff)
                .group_by(
                    ActivationEvent.event_name,
                    ActivationEvent.device_class,
                    ActivationEvent.auth_mode,
                    func.coalesce(ActivationEvent.reason_class, "none"),
                )
            )
        ).all()
        event_values = {
            (
                str(row.event_name),
                str(row.device_class),
                str(row.auth_mode),
                str(row.reason),
            ): int(row.account_count or 0)
            for row in event_rows
        }
        set_activation_event_accounts(event_values)
        _store_activation_scan_cache(current, funnel_values, event_values)

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
