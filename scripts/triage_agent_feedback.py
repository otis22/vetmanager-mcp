#!/usr/bin/env python3
"""Offline triage helper for agent feedback reports."""

from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from agent_feedback_service import sanitize_text, validate_agent_playbook, validate_match_rules_json
from storage import get_session_factory
from storage_models import AgentFeedbackReport, FEEDBACK_STATUS_LINKED, KnownIssue


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row_summary(report: AgentFeedbackReport) -> str:
    return (
        f"#{report.id} [{report.status}] {report.severity}/{report.category} "
        f"tool={report.related_tool or '-'} fingerprint={report.error_fingerprint_hash or '-'} "
        f"possible_pii={str(report.possible_pii).lower()} summary={report.summary}"
    )


async def _recent(args: argparse.Namespace) -> None:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(AgentFeedbackReport)
                .order_by(AgentFeedbackReport.created_at.desc(), AgentFeedbackReport.id.desc())
                .limit(args.limit)
            )
        ).scalars().all()
    for report in rows:
        print(_row_summary(report))


async def _group(args: argparse.Namespace) -> None:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(AgentFeedbackReport)
                .order_by(AgentFeedbackReport.created_at.desc(), AgentFeedbackReport.id.desc())
                .limit(args.limit)
            )
        ).scalars().all()
    groups: dict[tuple[str | None, str | None], list[AgentFeedbackReport]] = defaultdict(list)
    for report in rows:
        groups[(report.related_tool, report.error_fingerprint_hash)].append(report)
    for (tool, fingerprint), reports in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0][0] or "")):
        print(f"{len(reports):>4} tool={tool or '-'} fingerprint={fingerprint or '-'} latest=#{reports[0].id}")


def _load_json_file(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _safe_optional_text(value: str | None, *, limit: int) -> str | None:
    return sanitize_text(value, limit=limit) if value else None


def _sanitize_json_value(value: Any) -> Any:
    if isinstance(value, str):
        return sanitize_text(value, limit=1000) or ""
    if isinstance(value, list):
        return [_sanitize_json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_json_value(item) for key, item in value.items() if isinstance(key, str)}
    return value


def _safe_json_payload(data: dict[str, Any] | None, *, limit: int) -> str | None:
    if data is None:
        return None
    return json.dumps(_sanitize_json_value(data), ensure_ascii=True, sort_keys=True)[:limit]


async def _promote(args: argparse.Namespace) -> None:
    playbook = _load_json_file(args.playbook_json)
    playbook_json = _safe_json_payload(playbook, limit=8000)
    if playbook_json and validate_agent_playbook(playbook_json) is None:
        raise SystemExit("Invalid agent playbook JSON.")
    match_rules = _load_json_file(args.match_rules_json)
    match_rules_json = _safe_json_payload(match_rules, limit=8000)
    if match_rules_json and validate_match_rules_json(match_rules_json) is None:
        raise SystemExit("Invalid match rules JSON.")
    async with get_session_factory()() as session:
        report = await session.get(AgentFeedbackReport, args.report_id)
        if report is None:
            raise SystemExit(f"Report not found: {args.report_id}")
        now = _now()
        issue = KnownIssue(
            status=args.status,
            category=report.category,
            severity=report.severity,
            title=sanitize_text(args.title or report.summary, limit=240, required=True) or "",
            related_tool=report.related_tool,
            error_fingerprint_hash=report.error_fingerprint_hash,
            match_rules_json=match_rules_json,
            agent_playbook_json=playbook_json,
            public_summary=_safe_optional_text(args.public_summary, limit=2000),
            workaround=_safe_optional_text(args.workaround, limit=4000),
            report_count=1,
            first_seen_at=report.created_at or now,
            last_seen_at=now,
        )
        session.add(issue)
        await session.flush()
        report.known_issue_id = issue.id
        report.status = FEEDBACK_STATUS_LINKED
        await session.commit()
        print(f"created known_issue #{issue.id} from report #{report.id}")


async def _mark(args: argparse.Namespace) -> None:
    async with get_session_factory()() as session:
        issue = await session.get(KnownIssue, args.known_issue_id)
        if issue is None:
            raise SystemExit(f"Known issue not found: {args.known_issue_id}")
        issue.status = args.status
        await session.commit()
        print(f"known_issue #{issue.id} status={issue.status}")


async def _export(args: argparse.Namespace) -> None:
    async with get_session_factory()() as session:
        rows = (
            await session.execute(
                select(AgentFeedbackReport)
                .order_by(AgentFeedbackReport.created_at.desc(), AgentFeedbackReport.id.desc())
                .limit(args.limit)
            )
        ).scalars().all()
    groups: dict[tuple[str | None, str | None], list[AgentFeedbackReport]] = defaultdict(list)
    for report in rows:
        groups[(report.related_tool, report.error_fingerprint_hash)].append(report)
    print("# Agent Feedback Triage\n")
    for (tool, fingerprint), reports in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0][0] or "")):
        print(f"## {tool or 'unknown tool'} / {fingerprint or 'no fingerprint'}")
        print(f"- count: {len(reports)}")
        print(f"- latest_report_id: {reports[0].id}")
        print(f"- possible_pii: {str(any(report.possible_pii for report in reports)).lower()}")
        print(f"- sample_summary: {reports[0].summary}\n")


async def _retention(args: argparse.Namespace) -> None:
    cutoff = _now() - timedelta(days=args.days)
    async with get_session_factory()() as session:
        result = await session.execute(
            delete(AgentFeedbackReport)
            .where(AgentFeedbackReport.status.in_(("ignored", "linked", "triaged")))
            .where(AgentFeedbackReport.created_at < cutoff)
        )
        await session.commit()
    print(f"deleted_reports={result.rowcount or 0}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Triage DB-backed agent feedback.")
    sub = parser.add_subparsers(dest="command", required=True)

    recent = sub.add_parser("recent")
    recent.add_argument("--limit", type=int, default=50)
    recent.set_defaults(func=_recent)

    group = sub.add_parser("group")
    group.add_argument("--limit", type=int, default=500)
    group.set_defaults(func=_group)

    promote = sub.add_parser("promote")
    promote.add_argument("report_id", type=int)
    promote.add_argument("--title", default="")
    promote.add_argument("--status", default="acknowledged")
    promote.add_argument("--public-summary", default=None)
    promote.add_argument("--workaround", default=None)
    promote.add_argument("--playbook-json", default=None)
    promote.add_argument("--match-rules-json", default=None)
    promote.set_defaults(func=_promote)

    mark = sub.add_parser("mark")
    mark.add_argument("known_issue_id", type=int)
    mark.add_argument("status")
    mark.set_defaults(func=_mark)

    export = sub.add_parser("export-markdown")
    export.add_argument("--limit", type=int, default=500)
    export.set_defaults(func=_export)

    retention = sub.add_parser("retention-cleanup")
    retention.add_argument("--days", type=int, default=180)
    retention.set_defaults(func=_retention)
    return parser


def main() -> None:
    args = _build_parser().parse_args()
    asyncio.run(args.func(args))


if __name__ == "__main__":
    main()
