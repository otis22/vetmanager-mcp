"""Ad-hoc product metrics report for vetmanager-mcp (stage 110).

Read-only SQL snapshot of Accounts / Tokens / Requests / Failures.
Designed to run on prod via `docker compose exec mcp`:

    docker compose exec -T mcp python scripts/product_metrics_report.py

Exits 0 on success. Windowed by `--window=30d`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow running as `python scripts/product_metrics_report.py` without PYTHONPATH hacks.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
    TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
    TOKEN_EVENT_CREATED,
    TOKEN_EVENT_REVOKED,
)
from storage_models import (
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TokenUsageLog,
    TokenUsageStat,
    VetmanagerConnection,
)


FAILURE_EVENTS = (
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
)


def _to_aware(dt: datetime | None) -> datetime | None:
    """Normalize a datetime to UTC-aware form.

    **Invariant**: every naive datetime in our storage means UTC. This
    holds because all our columns declare `DateTime(timezone=True)` and
    are populated by `func.now()` (Postgres tz-aware) or by SQLAlchemy
    `datetime.now(timezone.utc)` call sites. SQLite, which ignores tz
    info and returns naive values, inherits the same semantics because
    only this code writes the data.

    If you ever manually edit DB rows or import from a non-UTC source,
    this assumption breaks and the report becomes silently wrong rather
    than crashing. Flagged by Codex review; acceptable trade-off for the
    single-operator, trusted-DB context (stage 110).
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


# ── helpers ────────────────────────────────────────────────────────────────


def _mask_email(email: str | None) -> str:
    """Return a PII-friendly masked form: `al***@ex***.com`."""
    if not email or "@" not in email:
        return "***"
    local, _, domain = email.partition("@")
    if "." not in domain:
        return "***@***"
    domain_name, _, tld = domain.rpartition(".")
    if len(local) < 3 or len(domain_name) < 3:
        return "***@***"
    return f"{local[:2]}***@{domain_name[:2]}***.{tld}"


async def _count_accounts(session, *, since: datetime | None = None) -> int:
    stmt = select(func.count()).select_from(Account)
    if since is not None:
        stmt = stmt.where(Account.created_at >= since)
    return int(await session.scalar(stmt) or 0)


async def _count_live_accounts(session, *, now: datetime, window: timedelta) -> int:
    """Accounts whose any token has `last_used_at` within `window`."""
    cutoff = now - window
    stmt = (
        select(func.count(func.distinct(ServiceBearerToken.account_id)))
        .select_from(TokenUsageStat)
        .join(ServiceBearerToken, ServiceBearerToken.id == TokenUsageStat.bearer_token_id)
        .where(TokenUsageStat.last_used_at >= cutoff)
    )
    return int(await session.scalar(stmt) or 0)


async def _count_dead_accounts(session, *, now: datetime) -> int:
    """Accounts registered > 30d ago with no request in last 30d.

    Implementation: fetch all accounts created > 30d ago, for each check
    max(last_used_at) across their tokens; count those where max is NULL
    or < now - 30d.

    **Scale caveat**: two-phase (IDs → `IN`-list → GROUP BY) is fine up
    to ~5k `old_accounts` across SQLite + Postgres. At 10k+ accounts the
    IN-list becomes the bottleneck — rewrite as a single CTE / subquery.
    Tracked for future refactor; not needed at current prod scale.
    """
    cutoff = now - timedelta(days=30)
    old_accounts = (
        await session.execute(
            select(Account.id).where(Account.created_at < cutoff)
        )
    ).scalars().all()
    if not old_accounts:
        return 0

    # Per-account max(last_used_at) via join through tokens.
    rows = await session.execute(
        select(
            Account.id,
            func.max(TokenUsageStat.last_used_at).label("last_used"),
        )
        .select_from(Account)
        .outerjoin(ServiceBearerToken, ServiceBearerToken.account_id == Account.id)
        .outerjoin(TokenUsageStat, TokenUsageStat.bearer_token_id == ServiceBearerToken.id)
        .where(Account.id.in_(old_accounts))
        .group_by(Account.id)
    )
    dead = 0
    for _, last_used in rows.all():
        last_used = _to_aware(last_used)
        if last_used is None or last_used < cutoff:
            dead += 1
    return dead


async def _fetch_dead_account_rows(session, *, now: datetime, limit: int = 50) -> list[dict[str, Any]]:
    cutoff = now - timedelta(days=30)
    rows = await session.execute(
        select(
            Account.id,
            Account.email,
            Account.created_at,
            func.max(TokenUsageStat.last_used_at).label("last_used"),
            func.count(func.distinct(ServiceBearerToken.id)).label("token_count"),
        )
        .select_from(Account)
        .outerjoin(ServiceBearerToken, ServiceBearerToken.account_id == Account.id)
        .outerjoin(TokenUsageStat, TokenUsageStat.bearer_token_id == ServiceBearerToken.id)
        .where(Account.created_at < cutoff)
        .group_by(Account.id, Account.email, Account.created_at)
    )
    out: list[dict[str, Any]] = []
    for acc_id, email, created, last_used, token_count in rows.all():
        last_used_aware = _to_aware(last_used)
        if last_used_aware is not None and last_used_aware >= cutoff:
            continue
        out.append({
            "account_id": acc_id,
            "email": _mask_email(email),
            "created_at": created.isoformat() if created else None,
            "last_request_at": last_used.isoformat() if last_used else None,
            "token_count": int(token_count or 0),
        })
    out.sort(key=lambda r: r["created_at"] or "")
    return out[:limit]


async def _count_accounts_without_tokens(session) -> int:
    stmt = (
        select(func.count())
        .select_from(Account)
        .outerjoin(ServiceBearerToken, ServiceBearerToken.account_id == Account.id)
        .where(ServiceBearerToken.id.is_(None))
    )
    return int(await session.scalar(stmt) or 0)


async def _count_accounts_without_active_connection(session) -> int:
    stmt = (
        select(func.count(Account.id))
        .select_from(Account)
        .outerjoin(
            VetmanagerConnection,
            and_(
                VetmanagerConnection.account_id == Account.id,
                VetmanagerConnection.status == "active",
            ),
        )
        .where(VetmanagerConnection.id.is_(None))
    )
    return int(await session.scalar(stmt) or 0)


async def _count_active_tokens(session, *, now: datetime) -> int:
    stmt = select(func.count()).select_from(ServiceBearerToken).where(
        ServiceBearerToken.status == TOKEN_STATUS_ACTIVE,
        or_(
            ServiceBearerToken.expires_at.is_(None),
            ServiceBearerToken.expires_at > now,
        ),
    )
    return int(await session.scalar(stmt) or 0)


async def _count_tokens_expiring_in(session, *, now: datetime, days: int) -> int:
    end = now + timedelta(days=days)
    stmt = select(func.count()).select_from(ServiceBearerToken).where(
        ServiceBearerToken.status == TOKEN_STATUS_ACTIVE,
        ServiceBearerToken.expires_at.isnot(None),
        ServiceBearerToken.expires_at > now,
        ServiceBearerToken.expires_at <= end,
    )
    return int(await session.scalar(stmt) or 0)


async def _count_events(
    session, *, event_type: str, since: datetime, until: datetime | None = None
) -> int:
    stmt = select(func.count()).select_from(TokenUsageLog).where(
        TokenUsageLog.event_type == event_type,
        TokenUsageLog.event_at >= since,
    )
    if until is not None:
        stmt = stmt.where(TokenUsageLog.event_at < until)
    return int(await session.scalar(stmt) or 0)


async def _failure_breakdown(session, *, since: datetime) -> dict[str, int]:
    rows = await session.execute(
        select(TokenUsageLog.event_type, func.count())
        .where(
            TokenUsageLog.event_type.in_(FAILURE_EVENTS),
            TokenUsageLog.event_at >= since,
        )
        .group_by(TokenUsageLog.event_type)
    )
    out: dict[str, int] = defaultdict(int)
    for event_type, count in rows.all():
        out[event_type] = int(count or 0)
    return dict(out)


async def _top_accounts_by_requests(
    session, *, top_n: int
) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(
            Account.id,
            Account.email,
            func.coalesce(func.sum(TokenUsageStat.request_count), 0).label("total"),
        )
        .select_from(Account)
        .join(ServiceBearerToken, ServiceBearerToken.account_id == Account.id)
        .join(TokenUsageStat, TokenUsageStat.bearer_token_id == ServiceBearerToken.id)
        .group_by(Account.id, Account.email)
        .order_by(func.sum(TokenUsageStat.request_count).desc())
        .limit(top_n)
    )
    return [
        {
            "account_id": acc_id,
            "email": _mask_email(email),
            "request_count": int(total or 0),
        }
        for acc_id, email, total in rows.all()
    ]


# ── orchestrator ───────────────────────────────────────────────────────────


async def collect_metrics(
    session_factory: async_sessionmaker,
    *,
    now: datetime,
    window_days: int = 30,
    top_n: int = 10,
) -> dict[str, Any]:
    """Collect all product-metrics counters in one read-only pass."""
    async with session_factory() as session:
        # Accounts
        total = await _count_accounts(session)
        new_24h = await _count_accounts(session, since=now - timedelta(hours=24))
        new_7d = await _count_accounts(session, since=now - timedelta(days=7))
        new_30d = await _count_accounts(session, since=now - timedelta(days=30))
        live_7d = await _count_live_accounts(session, now=now, window=timedelta(days=7))
        dead_30d = await _count_dead_accounts(session, now=now)
        no_tokens = await _count_accounts_without_tokens(session)
        no_connection = await _count_accounts_without_active_connection(session)
        dead_list = await _fetch_dead_account_rows(session, now=now)

        # Tokens
        active = await _count_active_tokens(session, now=now)
        expiring_7d = await _count_tokens_expiring_in(session, now=now, days=7)
        issued_24h = await _count_events(
            session, event_type=TOKEN_EVENT_CREATED,
            since=now - timedelta(hours=24),
        )
        revoked_24h = await _count_events(
            session, event_type=TOKEN_EVENT_REVOKED,
            since=now - timedelta(hours=24),
        )
        revoked_7d = await _count_events(
            session, event_type=TOKEN_EVENT_REVOKED,
            since=now - timedelta(days=7),
        )

        # Requests
        succeeded_24h = await _count_events(
            session, event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            since=now - timedelta(hours=24),
        )
        succeeded_7d = await _count_events(
            session, event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            since=now - timedelta(days=7),
        )
        succeeded_30d = await _count_events(
            session, event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
            since=now - timedelta(days=window_days),
        )
        top_accounts = await _top_accounts_by_requests(session, top_n=top_n)

        # Failures
        fail_24h = await _failure_breakdown(session, since=now - timedelta(hours=24))
        fail_7d = await _failure_breakdown(session, since=now - timedelta(days=7))
        fail_30d = await _failure_breakdown(session, since=now - timedelta(days=30))

    return {
        "accounts": {
            "total": total,
            "new_24h": new_24h,
            "new_7d": new_7d,
            "new_30d": new_30d,
            "live_7d": live_7d,
            "dead_30d": dead_30d,
            "no_tokens": no_tokens,
            "no_active_connection": no_connection,
            "dead_list": dead_list,
        },
        "tokens": {
            "total_active": active,
            "expiring_in_7d": expiring_7d,
            "issued_24h": issued_24h,
            "revoked_24h": revoked_24h,
            "revoked_7d": revoked_7d,
        },
        "requests": {
            "total_24h": succeeded_24h,
            "total_7d": succeeded_7d,
            "total_30d": succeeded_30d,
            "top_accounts": top_accounts,
        },
        "failures": {
            "by_event_24h": fail_24h,
            "by_event_7d": fail_7d,
            "by_event_30d": fail_30d,
        },
    }


# ── formatters ─────────────────────────────────────────────────────────────


def format_markdown(m: dict[str, Any], *, now: datetime, window_days: int) -> str:
    a, t, r, f = m["accounts"], m["tokens"], m["requests"], m["failures"]
    out: list[str] = []
    out.append("# Product metrics")
    out.append(f"_generated at {now.isoformat()} UTC, window {window_days}d_")
    out.append("")

    out.append("## Accounts")
    out.append(f"- total: **{a['total']}**")
    out.append(f"- new (24h / 7d / 30d): {a['new_24h']} / {a['new_7d']} / {a['new_30d']}")
    out.append(f"- live (request within 7d): **{a['live_7d']}**")
    out.append(f"- dead (registered >30d, no request in 30d): **{a['dead_30d']}**")
    out.append(f"- no tokens: {a['no_tokens']}")
    out.append(f"- no active vetmanager connection: {a['no_active_connection']}")
    out.append("")

    out.append("## Tokens")
    out.append(f"- active: **{t['total_active']}**")
    out.append(f"- expiring in 7d: {t['expiring_in_7d']}")
    out.append(f"- issued (24h): {t['issued_24h']}")
    out.append(f"- revoked (24h / 7d): {t['revoked_24h']} / {t['revoked_7d']}")
    out.append("")

    out.append("## Requests")
    out.append(f"- total (24h / 7d / 30d): {r['total_24h']} / {r['total_7d']} / {r['total_30d']}")
    out.append("")

    out.append("## Top accounts")
    if not r["top_accounts"]:
        out.append("_none_")
    else:
        out.append("| rank | account_id | email | requests |")
        out.append("|---|---|---|---|")
        for i, row in enumerate(r["top_accounts"], start=1):
            out.append(f"| {i} | {row['account_id']} | {row['email']} | {row['request_count']} |")
    out.append("")

    out.append("## Failures")
    out.append("| event | 24h | 7d | 30d |")
    out.append("|---|---|---|---|")
    for ev in FAILURE_EVENTS:
        out.append(
            f"| {ev} | {f['by_event_24h'].get(ev, 0)} "
            f"| {f['by_event_7d'].get(ev, 0)} | {f['by_event_30d'].get(ev, 0)} |"
        )
    out.append("")

    out.append("## Dead accounts")
    if not a["dead_list"]:
        out.append("_none_")
    else:
        out.append("| account_id | email | created_at | last_request_at | tokens |")
        out.append("|---|---|---|---|---|")
        for d in a["dead_list"]:
            out.append(
                f"| {d['account_id']} | {d['email']} | {d['created_at']} "
                f"| {d['last_request_at'] or '—'} | {d['token_count']} |"
            )
    return "\n".join(out)


def format_json(m: dict[str, Any], *, now: datetime, window_days: int) -> str:
    return json.dumps(
        {
            "generated_at": now.isoformat(),
            "window_days": window_days,
            "accounts": m["accounts"],
            "tokens": m["tokens"],
            "requests": m["requests"],
            "failures": m["failures"],
        },
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )


# ── entrypoint ─────────────────────────────────────────────────────────────


async def _async_main(args: argparse.Namespace) -> int:
    from storage import get_session_factory

    now = (
        datetime.fromisoformat(args.now_override).replace(tzinfo=timezone.utc)
        if args.now_override
        else datetime.now(timezone.utc)
    )
    factory = get_session_factory()
    m = await collect_metrics(
        factory, now=now, window_days=args.window_days, top_n=args.top_n
    )
    if args.format == "json":
        print(format_json(m, now=now, window_days=args.window_days))
    else:
        print(format_markdown(m, now=now, window_days=args.window_days))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Product metrics report for vetmanager-mcp.")
    p.add_argument("--window-days", type=int, default=30, help="Window in days for live/dead classification and aggregate request count.")
    p.add_argument("--format", choices=["markdown", "json"], default="markdown")
    p.add_argument("--top-n", type=int, default=10, help="Top-N accounts by request count.")
    p.add_argument("--now-override", type=str, default=None, help="ISO timestamp for deterministic testing only.")
    args = p.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    sys.exit(main())
