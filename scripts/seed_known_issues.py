#!/usr/bin/env python3
"""Seed verified known issues and run Stage 157 feedback diagnostics."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
from typing import Any
from uuid import uuid4

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastmcp.exceptions import ToolError
from sqlalchemy import func, select

import agent_feedback_service as feedback
from agent_feedback_service import (
    AUTO_EVENT_WRITE_TIMEOUT_SECONDS,
    FeedbackIncident,
    augment_tool_error,
    build_error_fingerprint_hash,
    normalize_error_text,
    validate_agent_playbook,
    validate_match_rules_json,
)
from storage import get_session_factory
from storage_models import Account, AgentFeedbackReport, KnownIssue, KnownIssueMatchEvent, ServiceBearerToken

SEED_STATUS = "workaround_available"
DIAGNOSTIC_TOOL = "__stage157_diagnostic__"
DIAGNOSTIC_MARKER = "stage157 synthetic feedback diagnostic"
DIAGNOSTIC_TITLE = "[seed:stage157-diagnostic] Stage 157 auto-event diagnostic"
_LONG_DIGIT_RE = re.compile(r"\d{6,}")
_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class SeedKnownIssuesError(RuntimeError):
    """Raised when seed application cannot safely proceed."""


@dataclass(frozen=True)
class SeedIssue:
    slug: str
    title: str
    category: str
    severity: str
    priority: int
    related_tool: str
    match_rules: dict[str, Any]
    agent_playbook: dict[str, Any]
    public_summary: str
    workaround: str


def _rules(tool: str, *markers: str) -> dict[str, Any]:
    return {
        "version": 1,
        "all": [
            {"field": "related_tool", "op": "eq", "value": tool},
            {"field": "error_code", "op": "eq", "value": "ToolError"},
            {"field": "normalized_error_text", "op": "contains_any", "value": list(markers)},
        ],
    }


def _playbook(
    summary: str,
    *,
    steps: list[str],
    do_not_do: list[str],
    tools: list[str],
    safe_to_retry: bool = True,
) -> dict[str, Any]:
    return {
        "version": 1,
        "summary": summary,
        "steps": steps,
        "do_not_do": do_not_do,
        "recommended_tool_sequence": tools,
        "safe_to_retry": safe_to_retry,
    }


SEED_ISSUES: tuple[SeedIssue, ...] = (
    SeedIssue(
        slug="admission-create-date-field",
        title="[seed:admission-create-date-field] Admission create uses admission_date",
        category="contract",
        severity="medium",
        priority=40,
        related_tool="create_admission",
        match_rules=_rules("create_admission", "admission_date", "date ignored", "date field"),
        agent_playbook=_playbook(
            "Admission create expects admission_date in YYYY-MM-DD HH:MM:SS format.",
            steps=["Retry with admission_date instead of date.", "Use YYYY-MM-DD HH:MM:SS without timezone."],
            do_not_do=["Do not send a top-level date field for admission create."],
            tools=["create_admission"],
        ),
        public_summary="Vetmanager admission create uses admission_date, not date.",
        workaround="Map appointment datetime to admission_date before create_admission.",
    ),
    SeedIssue(
        slug="hospitalization-create-fields",
        title="[seed:hospitalization-create-fields] Hospitalization fields use VM names",
        category="contract",
        severity="medium",
        priority=45,
        related_tool="create_hospitalization",
        match_rules=_rules("create_hospitalization", "hospital_block_id", "date_in", "date_out", "block_id"),
        agent_playbook=_playbook(
            "Hospitalization create/update maps block and dates to hospital_block_id/date_in/date_out.",
            steps=["Use block_id input only through the MCP tool.", "Keep date_in/date_out as VM datetime strings."],
            do_not_do=["Do not send camelCase dateIn/dateOut or raw blockId to Vetmanager."],
            tools=["create_hospitalization"],
        ),
        public_summary="Hospitalization payloads use hospital_block_id, date_in and date_out.",
        workaround="Use the MCP create_hospitalization contract and avoid raw Vetmanager field aliases.",
    ),
    SeedIssue(
        slug="vaccinations-special-endpoint",
        title="[seed:vaccinations-special-endpoint] Vaccinations use pet_id special endpoint",
        category="contract",
        severity="medium",
        priority=50,
        related_tool="get_vaccinations",
        match_rules=_rules("get_vaccinations", "medicalcards", "pet_id", "vaccination"),
        agent_playbook=_playbook(
            "Vaccinations are served by a special endpoint with top-level pet_id and data.medicalcards.",
            steps=["Pass pet_id to get_vaccinations.", "Read vaccination rows from data.medicalcards."],
            do_not_do=["Do not use generic filter/sort assumptions for MedicalCards/Vaccinations."],
            tools=["get_vaccinations"],
        ),
        public_summary="MedicalCards/Vaccinations is a special-case endpoint.",
        workaround="Use get_vaccinations(pet_id=...) instead of generic MedicalCard filters.",
    ),
    SeedIssue(
        slug="messages-reports-campaign",
        title="[seed:messages-reports-campaign] Message reports require campaign",
        category="contract",
        severity="medium",
        priority=55,
        related_tool="get_message_reports",
        match_rules=_rules("get_message_reports", "campaign", "campaign name cannot be empty", "messages reports"),
        agent_playbook=_playbook(
            "Message reports require a non-empty campaign query parameter.",
            steps=["Ask for or reuse the campaign name.", "Call get_message_reports with campaign set."],
            do_not_do=["Do not rely on generic filter[] alone for messages/reports."],
            tools=["get_message_reports"],
        ),
        public_summary="messages/reports requires top-level campaign.",
        workaround="Provide campaign explicitly when requesting message reports.",
    ),
    SeedIssue(
        slug="breed-filter-pet-type-id",
        title="[seed:breed-filter-pet-type-id] Breed filter uses pet_type_id",
        category="contract",
        severity="medium",
        priority=60,
        related_tool="get_breeds",
        match_rules=_rules("get_breeds", "pet_type_id", "pettypeid", "breed filter"),
        agent_playbook=_playbook(
            "Breed list filters by pet_type_id.",
            steps=["Use pet_type_id for breed filtering."],
            do_not_do=["Do not use petTypeId in raw filter properties."],
            tools=["get_breeds"],
        ),
        public_summary="Breed filter property is pet_type_id.",
        workaround="Normalize pet type filter to pet_type_id before querying breeds.",
    ),
    SeedIssue(
        slug="timesheet-day-overlap",
        title="[seed:timesheet-day-overlap] Timesheet day filter uses overlap",
        category="contract",
        severity="medium",
        priority=65,
        related_tool="get_timesheets",
        match_rules=_rules("get_timesheets", "begin_datetime", "end_datetime", "night shift", "overlap"),
        agent_playbook=_playbook(
            "Timesheet day filtering must use overlap on begin_datetime/end_datetime.",
            steps=["Use begin_datetime < next day and end_datetime > day start.", "Keep night shifts that cross midnight."],
            do_not_do=["Do not use containment begin>=day_start AND end<=day_end."],
            tools=["get_timesheets"],
        ),
        public_summary="Timesheet day queries must include overlapping night shifts.",
        workaround="Use overlap predicate for day schedules instead of strict containment.",
    ),
    SeedIssue(
        slug="report-ai-goods-good-id-preview",
        title="[seed:report-ai-goods-good-id-preview] Report AI goods preview fails on good.id",
        category="bug",
        severity="medium",
        priority=35,
        related_tool="get_report_ai_job_data",
        match_rules={
            "version": 1,
            "all": [
                {"field": "related_tool", "op": "eq", "value": "get_report_ai_job_data"},
                {"field": "error_code", "op": "eq", "value": "ToolError"},
                {
                    "field": "normalized_error_text",
                    "op": "contains_any",
                    "value": ["preview_failed", "preview failed"],
                },
                {
                    "field": "normalized_error_text",
                    "op": "contains_any",
                    "value": [
                        "good.id",
                        "`good`.`id`",
                        '"good"."id"',
                        "good id",
                        "goods good",
                        "товар",
                    ],
                },
            ],
        },
        agent_playbook=_playbook(
            "Report AI goods preview can fail when generated SQL references a standalone good.id field.",
            steps=[
                "Read report_ai_prompt_helper before retrying.",
                "Rephrase the Russian intent to request product code/article/title instead of standalone good.id.",
                "Create a new Report AI job and poll it with get_report_ai_job.",
            ],
            do_not_do=[
                "Do not ask Report AI to output a standalone good.id column.",
                "Do not expose or edit raw SQL in MCP output.",
            ],
            tools=["create_report_ai_job", "get_report_ai_job"],
        ),
        public_summary="Report AI goods preview may fail when the generated query references good.id.",
        workaround="Retry with an intent asking for product code/article/title instead of standalone good.id.",
    ),
)


def seed_marker(slug: str) -> str:
    return f"[seed:{slug}]"


def _json_payload(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def validate_seed_definitions() -> None:
    seen: set[str] = set()
    for item in SEED_ISSUES:
        marker = seed_marker(item.slug)
        if item.slug in seen:
            raise SeedKnownIssuesError(f"duplicate_seed_slug:{item.slug}")
        seen.add(item.slug)
        if not item.title.startswith(f"{marker} "):
            raise SeedKnownIssuesError(f"invalid_seed_title:{item.slug}")
        if validate_match_rules_json(_json_payload(item.match_rules)) is None:
            raise SeedKnownIssuesError(f"invalid_match_rules:{item.slug}")
        if validate_agent_playbook(_json_payload(item.agent_playbook)) is None:
            raise SeedKnownIssuesError(f"invalid_agent_playbook:{item.slug}")


def _issue_values(item: SeedIssue) -> dict[str, Any]:
    return {
        "status": SEED_STATUS,
        "category": item.category,
        "severity": item.severity,
        "priority": item.priority,
        "related_tool": item.related_tool,
        "match_rules_json": _json_payload(item.match_rules),
        "agent_playbook_json": _json_payload(item.agent_playbook),
        "public_summary": item.public_summary,
        "workaround": item.workaround,
    }


async def seed_known_issues(*, apply: bool) -> dict[str, int | str]:
    validate_seed_definitions()
    summary = {"status": "ok", "created": 0, "updated": 0, "unchanged": 0, "skipped": 0}
    async with get_session_factory()() as session:
        for item in SEED_ISSUES:
            marker = seed_marker(item.slug)
            rows = (
                await session.execute(
                    select(KnownIssue).where(KnownIssue.title.like(f"{marker} %"))
                )
            ).scalars().all()
            if len(rows) > 1:
                raise SeedKnownIssuesError(f"duplicate_seed_rows:{item.slug}")
            values = _issue_values(item)
            if not rows:
                summary["created"] += 1
                if apply:
                    session.add(KnownIssue(title=item.title, **values))
                continue
            issue = rows[0]
            changed = issue.title != item.title or any(getattr(issue, key) != value for key, value in values.items())
            if changed:
                summary["updated"] += 1
                if apply:
                    issue.title = item.title
                    for key, value in values.items():
                        setattr(issue, key, value)
            else:
                summary["unchanged"] += 1
        if apply:
            await session.commit()
        else:
            await session.rollback()
    return summary


def generate_run_id() -> str:
    chunks = [uuid4().hex[index:index + 4] for index in range(0, 32, 4)]
    return "rid-" + "-".join(chunks)


def _run_id_is_safe(run_id: str) -> bool:
    return (
        bool(re.fullmatch(r"[a-z0-9-]{8,80}", run_id))
        and not _LONG_DIGIT_RE.search(run_id)
        and not _ISO_DATE_RE.search(run_id)
        and normalize_error_text(run_id) == run_id
    )


def _diagnostic_rules() -> dict[str, Any]:
    return _rules(DIAGNOSTIC_TOOL, DIAGNOSTIC_MARKER)


async def _ensure_diagnostic_issue(session) -> KnownIssue:
    rows = (
        await session.execute(
            select(KnownIssue).where(KnownIssue.title.like("[seed:stage157-diagnostic] %"))
        )
    ).scalars().all()
    if len(rows) > 1:
        raise SeedKnownIssuesError("duplicate_seed_rows:stage157-diagnostic")
    values = {
        "status": "acknowledged",
        "category": "bug",
        "severity": "low",
        "priority": 999,
        "related_tool": DIAGNOSTIC_TOOL,
        "match_rules_json": _json_payload(_diagnostic_rules()),
        "agent_playbook_json": None,
        "public_summary": "Synthetic Stage 157 feedback auto-event diagnostic.",
        "workaround": "Operator diagnostic only; not an agent-facing known issue.",
    }
    if rows:
        issue = rows[0]
        for key, value in values.items():
            setattr(issue, key, value)
        return issue
    issue = KnownIssue(title=DIAGNOSTIC_TITLE, **values)
    session.add(issue)
    await session.flush()
    return issue


async def _count_auto_rows(*, fingerprint: str, account_id: int | None, bearer_token_id: int | None) -> tuple[int, int]:
    event_query = (
        select(func.count())
        .select_from(KnownIssueMatchEvent)
        .where(KnownIssueMatchEvent.source == "auto")
        .where(KnownIssueMatchEvent.error_fingerprint_hash == fingerprint)
    )
    report_query = (
        select(func.count())
        .select_from(AgentFeedbackReport)
        .where(AgentFeedbackReport.source == "auto")
        .where(AgentFeedbackReport.error_fingerprint_hash == fingerprint)
    )
    if account_id is not None:
        event_query = event_query.where(KnownIssueMatchEvent.account_id == account_id)
        report_query = report_query.where(AgentFeedbackReport.account_id == account_id)
    if bearer_token_id is not None:
        event_query = event_query.where(KnownIssueMatchEvent.bearer_token_id == bearer_token_id)
        report_query = report_query.where(AgentFeedbackReport.bearer_token_id == bearer_token_id)
    async with get_session_factory()() as session:
        return int((await session.scalar(event_query)) or 0), int((await session.scalar(report_query)) or 0)


async def _validate_diagnostic_identity(
    *, account_id: int | None, bearer_token_id: int | None,
) -> dict[str, Any] | None:
    missing: list[str] = []
    async with get_session_factory()() as session:
        account = None
        token = None
        if account_id is not None:
            account = await session.get(Account, account_id)
            if account is None or account.status != "active":
                missing.append("account_id")
        if bearer_token_id is not None:
            token = await session.get(ServiceBearerToken, bearer_token_id)
            if token is None or not token.is_active():
                missing.append("bearer_token_id")
        if missing:
            return {
                "status": "failed",
                "skipped_reason": "identity_not_found",
                "missing": ",".join(missing),
                "account_id_present": account is not None,
                "bearer_token_id_present": token is not None,
            }
        if account_id is not None and token is not None and token.account_id != account_id:
            return {
                "status": "failed",
                "skipped_reason": "identity_mismatch",
                "account_id": account_id,
                "token_account_id": token.account_id,
                "account_id_present": True,
                "bearer_token_id_present": True,
            }
    return None


async def diagnostic_auto_event(
    *,
    apply: bool,
    account_id: int | None,
    bearer_token_id: int | None,
    run_id: str | None = None,
) -> dict[str, Any]:
    if not apply:
        return {
            "status": "skipped",
            "skipped_reason": "dry_run",
            "account_id_present": account_id is not None,
            "bearer_token_id_present": bearer_token_id is not None,
        }
    if not os.environ.get("FEEDBACK_FINGERPRINT_PEPPER", "").strip():
        return {"status": "failed", "skipped_reason": "missing_feedback_fingerprint_pepper"}
    if account_id is None and bearer_token_id is None:
        return {"status": "failed", "skipped_reason": "missing_identity"}
    current_run_id = run_id or generate_run_id()
    if not _run_id_is_safe(current_run_id):
        return {"status": "failed", "skipped_reason": "unsafe_run_id", "run_id": current_run_id}

    error_message = f"{DIAGNOSTIC_MARKER} {current_run_id}"
    incident = FeedbackIncident(
        related_tool=DIAGNOSTIC_TOOL,
        error_code="ToolError",
        error_excerpt=error_message,
    )
    fingerprint = build_error_fingerprint_hash(incident)
    if fingerprint is None:
        return {"status": "failed", "skipped_reason": "missing_feedback_fingerprint_pepper"}
    identity_error = await _validate_diagnostic_identity(account_id=account_id, bearer_token_id=bearer_token_id)
    if identity_error is not None:
        return identity_error

    async with get_session_factory()() as session:
        await _ensure_diagnostic_issue(session)
        await session.commit()

    before_events, before_reports = await _count_auto_rows(
        fingerprint=fingerprint,
        account_id=account_id,
        bearer_token_id=bearer_token_id,
    )
    credentials = SimpleNamespace(
        account_id=account_id,
        bearer_token_id=bearer_token_id,
    )
    started = time.monotonic()
    await augment_tool_error(DIAGNOSTIC_TOOL, credentials, ToolError(error_message))
    elapsed_ms = (time.monotonic() - started) * 1000.0
    after_events, after_reports = await _count_auto_rows(
        fingerprint=fingerprint,
        account_id=account_id,
        bearer_token_id=bearer_token_id,
    )
    event_created = after_events > before_events
    report_created = after_reports > before_reports
    if not event_created:
        return {
            "status": "failed",
            "skipped_reason": "wrapper_auto_event_missing",
            "event_created": False,
            "report_created": False,
            "elapsed_ms": elapsed_ms,
            "error_fingerprint_hash": fingerprint,
            "account_id_present": account_id is not None,
            "bearer_token_id_present": bearer_token_id is not None,
        }
    status = "ok"
    skipped_reason = None
    if elapsed_ms > AUTO_EVENT_WRITE_TIMEOUT_SECONDS * 1000:
        status = "failed"
        skipped_reason = "auto_event_timeout_risk"
    elif not report_created:
        skipped_reason = "dedup_or_cap_suppressed"
    return {
        "status": status,
        "skipped_reason": skipped_reason,
        "event_created": event_created,
        "report_created": report_created,
        "elapsed_ms": elapsed_ms,
        "error_fingerprint_hash": fingerprint,
        "run_id": current_run_id,
        "account_id_present": account_id is not None,
        "bearer_token_id_present": bearer_token_id is not None,
    }


def _print_summary(summary: dict[str, Any]) -> None:
    print(" ".join(f"{key}={value}" for key, value in summary.items() if value is not None))


async def _main_async(args: argparse.Namespace) -> int:
    if args.command == "diagnostic-auto-event":
        summary = await diagnostic_auto_event(
            apply=args.apply,
            account_id=args.account_id,
            bearer_token_id=args.bearer_token_id,
            run_id=args.run_id,
        )
        _print_summary(summary)
        return 0 if summary.get("status") in {"ok", "skipped"} else 1
    summary = await seed_known_issues(apply=args.apply)
    _print_summary(summary)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Stage 157 known issues.")
    parser.add_argument("--dry-run", action="store_true", help="Validate and report planned seed changes.")
    parser.add_argument("--apply", action="store_true", help="Apply seed changes.")
    sub = parser.add_subparsers(dest="command")
    diagnostic = sub.add_parser("diagnostic-auto-event")
    diagnostic.add_argument("--apply", action="store_true")
    diagnostic.add_argument("--dry-run", action="store_true")
    diagnostic.add_argument("--account-id", type=int, default=None)
    diagnostic.add_argument("--bearer-token-id", type=int, default=None)
    diagnostic.add_argument("--run-id", default=None)
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.command is None:
        if args.apply == args.dry_run:
            parser.error("choose exactly one of --dry-run or --apply")
    elif args.command == "diagnostic-auto-event":
        if args.apply == args.dry_run:
            parser.error("choose exactly one of --dry-run or --apply")
    raise SystemExit(asyncio.run(_main_async(args)))


if __name__ == "__main__":
    main()
