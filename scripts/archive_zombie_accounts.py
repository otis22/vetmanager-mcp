#!/usr/bin/env python3
"""Archive and restore zombie accounts without exposing account PII."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from sqlalchemy import exists, or_, select, update

from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_DISABLED,
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
    TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
)
from storage import get_session_factory
from storage_models import (
    Account,
    AgentFeedbackReport,
    KnownIssueMatchEvent,
    ServiceBearerToken,
    TokenUsageLog,
    TokenUsageStat,
    VetmanagerConnection,
)


REQUEST_HISTORY_EVENTS = (
    TOKEN_EVENT_AUTH_SUCCEEDED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_FAILED_REVOKED,
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_DISABLED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_FAILED_NO_SCOPES,
    TOKEN_EVENT_AUTH_FAILED_NO_CONNECTION,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _candidate_id_select(*, now: datetime):
    cutoff = now - timedelta(days=30)
    active_connection_exists = exists(
        select(VetmanagerConnection.id).where(
            VetmanagerConnection.account_id == Account.id,
            VetmanagerConnection.status == "active",
        )
    )
    usage_stat_exists = exists(
        select(TokenUsageStat.id)
        .join(ServiceBearerToken, ServiceBearerToken.id == TokenUsageStat.bearer_token_id)
        .where(
            ServiceBearerToken.account_id == Account.id,
            or_(TokenUsageStat.request_count > 0, TokenUsageStat.last_used_at.isnot(None)),
        )
    )
    request_log_exists = exists(
        select(TokenUsageLog.id)
        .join(ServiceBearerToken, ServiceBearerToken.id == TokenUsageLog.bearer_token_id)
        .where(
            ServiceBearerToken.account_id == Account.id,
            TokenUsageLog.event_type.in_(REQUEST_HISTORY_EVENTS),
        )
    )
    feedback_exists = exists(
        select(AgentFeedbackReport.id).where(AgentFeedbackReport.account_id == Account.id)
    )
    match_event_exists = exists(
        select(KnownIssueMatchEvent.id).where(KnownIssueMatchEvent.account_id == Account.id)
    )
    return (
        select(Account.id)
        .where(Account.archived_at.is_(None))
        .where(Account.created_at < cutoff)
        .where(~active_connection_exists)
        .where(~usage_stat_exists)
        .where(~request_log_exists)
        .where(~feedback_exists)
        .where(~match_event_exists)
        .order_by(Account.id)
    )


async def _candidate_ids(session, *, now: datetime) -> list[int]:
    return list((await session.execute(_candidate_id_select(now=now))).scalars().all())


async def archive_zombie_accounts(*, apply: bool, now: datetime | None = None) -> dict[str, Any]:
    current_now = now or _now()
    async with get_session_factory()() as session:
        ids = await _candidate_ids(session, now=current_now)
        archived_ids: list[int] = []
        if apply and ids:
            result = await session.execute(
                update(Account)
                .where(Account.id.in_(ids))
                .where(Account.id.in_(_candidate_id_select(now=current_now)))
                .values(archived_at=current_now)
                .returning(Account.id)
                .execution_options(synchronize_session=False)
            )
            archived_ids = sorted(result.scalars().all())
            await session.commit()
        elif not apply:
            await session.rollback()
        return {
            "status": "ok",
            "matched": len(ids),
            "archived": len(archived_ids) if apply else 0,
            "unchanged": 0,
            "skipped": max(0, len(ids) - len(archived_ids)) if apply else 0,
            "candidate_ids": ids,
            "archived_ids": archived_ids,
        }


async def restore_account(account_id: int, *, apply: bool) -> dict[str, int | str]:
    async with get_session_factory()() as session:
        account = await session.get(Account, account_id)
        if account is None:
            return {
                "status": "not_found",
                "restored": 0,
                "already_active": 0,
                "not_found": 1,
                "account_id": account_id,
            }
        if account.archived_at is None:
            await session.rollback()
            return {
                "status": "ok",
                "restored": 0,
                "already_active": 1,
                "not_found": 0,
                "account_id": account_id,
            }
        if apply:
            account.archived_at = None
            await session.commit()
        else:
            await session.rollback()
        summary = {
            "status": "ok",
            "restored": 1 if apply else 0,
            "already_active": 0,
            "not_found": 0,
            "account_id": account_id,
        }
        if not apply:
            summary["would_restore"] = 1
        return summary


def _format_value(value: Any) -> str:
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return str(value)


def _print_summary(summary: dict[str, Any]) -> None:
    print(" ".join(f"{key}={_format_value(value)}" for key, value in summary.items()))


async def _main_async(args: argparse.Namespace) -> int:
    if args.command == "restore":
        summary = await restore_account(args.account_id, apply=args.apply)
        _print_summary(summary)
        return 0 if summary["status"] == "ok" else 1
    summary = await archive_zombie_accounts(apply=args.apply)
    _print_summary(summary)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Archive Stage 158 zombie accounts without printing PII.")
    parser.add_argument("--dry-run", action="store_true", help="Report archive candidates without mutating DB.")
    parser.add_argument("--apply", action="store_true", help="Archive matching zombie accounts.")
    sub = parser.add_subparsers(dest="command")
    restore = sub.add_parser("restore")
    restore.add_argument("--account-id", type=int, required=True)
    restore.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    restore.add_argument("--apply", action="store_true", default=argparse.SUPPRESS)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        if args.apply == args.dry_run:
            parser.error("choose exactly one of --dry-run or --apply")
    elif args.command == "restore":
        if args.apply == args.dry_run:
            parser.error("choose exactly one of --dry-run or --apply")
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
