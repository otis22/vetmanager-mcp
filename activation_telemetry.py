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
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    CONNECTION_STATUS_ACTIVE,
    OAUTH_STATUS_ACTIVE,
    TOKEN_STATUS_ACTIVE,
    Account,
    ActivationEvent,
    OAuthAccessToken,
    OAuthGrant,
    ServiceBearerToken,
    TokenUsageLog,
    TokenUsageStat,
    VetmanagerConnection,
)

def _latest(*values: datetime | None) -> datetime | None:
    """Most recent of the given timestamps, ignoring the missing ones."""
    present = [
        value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        for value in values
        if value is not None
    ]
    return max(present) if present else None


async def _accounts_with_requests(session, *, since: datetime | None = None) -> set[int]:
    """Accounts that authenticated at least once, on either channel (stage 260).

    Reads the journal instead of the bearer tokens: an account working through
    OAuth has no bearer token at all and used to look like it never called.
    """
    stmt = (
        select(TokenUsageLog.account_id)
        .where(TokenUsageLog.event_type == TOKEN_EVENT_AUTH_SUCCEEDED)
        .where(TokenUsageLog.account_id.is_not(None))
    )
    if since is not None:
        stmt = stmt.where(TokenUsageLog.event_at >= since)
    return {int(account_id) for account_id in (await session.execute(stmt)).scalars().all()}


async def _accounts_with_live_oauth_access(session, *, now: datetime) -> set[int]:
    """Accounts holding a usable OAuth grant — the OAuth counterpart of an active token."""
    stmt = (
        select(OAuthGrant.account_id)
        .join(OAuthAccessToken, OAuthAccessToken.grant_id == OAuthGrant.id)
        .where(OAuthGrant.status == OAUTH_STATUS_ACTIVE)
        .where(OAuthAccessToken.status == OAUTH_STATUS_ACTIVE)
        .where(OAuthAccessToken.expires_at > now)
    )
    return {int(account_id) for account_id in (await session.execute(stmt)).scalars().all()}


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
        # Stage 260: an OAuth grant is access too. Without it the funnel drops
        # every account that never issued a bearer token.
        oauth_access_account_ids = await _accounts_with_live_oauth_access(session, now=current)
        active_token_account_ids |= oauth_access_account_ids
        recent_usage_account_ids |= await _accounts_with_requests(
            session, since=recent_usage_cutoff
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
                    .where(ServiceBearerToken.status == TOKEN_STATUS_ACTIVE)
                    .where(
                        or_(
                            ServiceBearerToken.expires_at.is_(None),
                            ServiceBearerToken.expires_at > current,
                        )
                    )
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
        # Stage 260: the journal is the channel-neutral answer to "did they call".
        first_mcp_request_ids |= (await _accounts_with_requests(session)) & new_account_ids
        funnel_values = {
            "registered": len(account_ids),
            "connected": len(connected_account_ids),
            "with_active_tokens": len(account_ids & active_token_account_ids),
            "ready_for_mcp": len(connected_with_active_token_ids),
            "with_recent_usage_7d": len(connected_recent_usage_ids),
            "new_registered": len(new_account_ids),
            "integration_saved": len(integration_saved_ids),
            "token_issued": len(integration_saved_ids & token_issued_ids),
            "token_copied": len(integration_saved_ids & token_issued_ids & token_copied_ids),
            "first_mcp_request": len(integration_saved_ids & first_mcp_request_ids),
        }
        set_activation_funnel_accounts(funnel_values)
        reason = func.coalesce(ActivationEvent.reason_class, "none")
        event_rows = (
            await session.execute(
                select(
                    ActivationEvent.event_name,
                    ActivationEvent.device_class,
                    ActivationEvent.auth_mode,
                    reason.label("reason"),
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
                    reason,
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
            func.max(ServiceBearerToken.last_used_at).label("token_last_used_at"),
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

    # Stage 260: "when did this account last call" now comes from the journal,
    # which covers both channels; `ServiceBearerToken.last_used_at` only ever
    # answered for one of them.
    last_request_by_account = {
        int(account_id): last_at
        for account_id, last_at in (
            await session.execute(
                select(
                    TokenUsageLog.account_id,
                    func.max(TokenUsageLog.event_at),
                )
                .where(TokenUsageLog.event_type == TOKEN_EVENT_AUTH_SUCCEEDED)
                .where(TokenUsageLog.account_id.is_not(None))
                .group_by(TokenUsageLog.account_id)
            )
        ).all()
    }

    # Accounts whose only access is OAuth have no bearer row above, so they are
    # added here with the grant as the age anchor.
    oauth_rows = (
        await session.execute(
            select(
                OAuthGrant.account_id.label("account_id"),
                func.min(OAuthGrant.created_at).label("earliest_grant_created_at"),
            )
            .join(Account, Account.id == OAuthGrant.account_id)
            .where(Account.status == ACCOUNT_STATUS_ACTIVE)
            .where(OAuthGrant.status == OAUTH_STATUS_ACTIVE)
            .where(
                exists()
                .where(VetmanagerConnection.account_id == Account.id)
                .where(VetmanagerConnection.status == CONNECTION_STATUS_ACTIVE)
            )
            .group_by(OAuthGrant.account_id)
        )
    ).all()
    bearer_account_ids = {int(row.account_id) for row in rows}
    oauth_only_rows = [row for row in oauth_rows if int(row.account_id) not in bearer_account_ids]

    gauges: dict[int, float] = {}
    live_account_ids: set[int] = set()
    emitted = 0
    # The fallback anchor keeps its own name per channel: existing alerting
    # reads `age_anchor`, and "token_created_at" must keep meaning a token.
    anchored_accounts: list[tuple[int, datetime | None, datetime | None, int, str]] = [
        (
            int(row.account_id),
            row.token_last_used_at,
            row.earliest_token_created_at,
            int(row.live_token_count or 0),
            "token_created_at",
        )
        for row in rows
    ] + [
        (int(row.account_id), None, row.earliest_grant_created_at, 0, "oauth_grant_created_at")
        for row in oauth_only_rows
    ]

    for (
        account_id,
        token_last_used_at,
        earliest_access_at,
        live_token_count,
        fallback_anchor,
    ) in anchored_accounts:
        live_account_ids.add(account_id)
        # The journal covers both channels but only from stage 260 onward;
        # the token's own marker still answers for everything before it.
        last_request_at = _latest(
            last_request_by_account.get(account_id),
            token_last_used_at,
        )
        anchor_at = last_request_at or earliest_access_at
        if anchor_at is None:
            continue

        age_hours = _hours_between(current, anchor_at)
        gauges[account_id] = age_hours

        if age_hours < SILENCE_THRESHOLDS_HOURS[0]:
            _clear_account_dedup(account_id)
            continue

        ever_used = last_request_at is not None
        age_anchor = "last_request_at" if ever_used else fallback_anchor
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
                    "live_token_count": live_token_count,
                },
            )

    for account_id, _threshold in list(_ALERTED_THRESHOLDS):
        if account_id not in live_account_ids:
            _clear_account_dedup(account_id)
    set_account_last_request_age_hours(gauges)
    return emitted
