"""Stage 151 — Known issue match analytics events.

Targeted regression tests for the new `known_issue_match_events` table and
write-path integration into agent_feedback_service.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

import agent_feedback_service as feedback
from storage_models import AgentFeedbackReport, KnownIssue, KnownIssueMatchEvent
from tests.runtime_factories import make_runtime_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage151-test-pepper")


# ─── AC #2 + AC #10: model schema, privacy whitelist ────────────────────────


def test_ac2_model_has_required_columns_only() -> None:
    """Schema columns are restricted to the privacy-safe whitelist."""
    cols = {c.name for c in KnownIssueMatchEvent.__table__.columns}
    expected = {
        "id",
        "created_at",
        "known_issue_id",
        "related_tool",
        "error_fingerprint_hash",
        "account_id",
        "bearer_token_id",
        "source",
    }
    assert cols == expected, f"Schema drift detected: {cols ^ expected}"


def test_ac10_model_has_no_raw_text_columns() -> None:
    """Privacy contract: raw bug-report text never lands in match events."""
    cols = {c.name for c in KnownIssueMatchEvent.__table__.columns}
    forbidden = {"summary", "details", "error_excerpt", "params_shape_json", "suggested_fix", "reproduce"}
    overlap = cols & forbidden
    assert overlap == set(), f"Raw-text columns leaked into events schema: {overlap}"


def test_ac2_model_has_check_constraint_on_source() -> None:
    constraints = [c.name for c in KnownIssueMatchEvent.__table__.constraints]
    assert any("source" in (name or "") for name in constraints), (
        "AC #2: CHECK constraint on source IN (injection|report|auto) missing"
    )


def test_ac2_model_has_required_indexes() -> None:
    index_names = {idx.name for idx in KnownIssueMatchEvent.__table__.indexes}
    assert "ix_known_issue_match_events_known_issue_created" in index_names
    assert "ix_known_issue_match_events_account_created" in index_names


# ─── AC #3 + AC #7: helper non-throwing + commit-contract ─────────────────────


@pytest.mark.asyncio
async def test_ac3_write_helper_stages_row_without_commit(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    """Helper only `session.add`s — caller owns commit."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "f.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        issue = KnownIssue(
            status="open", category="bug", severity="medium",
            title="Test", related_tool="get_payments",
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)

    async with session_factory() as session:
        await feedback.write_known_issue_match_event(
            session,
            known_issue_id=issue.id,
            related_tool="get_payments",
            error_fingerprint_hash="hmac-sha256:abc",
            account_id=None,
            bearer_token_id=42,
            source="injection",
        )
        # Without commit — nothing persisted yet (rolled back on context exit).
    async with session_factory() as session:
        rows_before_commit = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert rows_before_commit == [], "AC #3: helper must NOT auto-commit; caller-owned"

    # Now caller commits explicitly.
    async with session_factory() as session:
        await feedback.write_known_issue_match_event(
            session,
            known_issue_id=issue.id,
            related_tool="get_payments",
            error_fingerprint_hash="hmac-sha256:abc",
            account_id=None,
            bearer_token_id=42,
            source="injection",
        )
        await session.commit()
    async with session_factory() as session:
        rows = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "injection"
    assert rows[0].related_tool == "get_payments"
    assert rows[0].error_fingerprint_hash == "hmac-sha256:abc"
    assert rows[0].bearer_token_id == 42
    assert rows[0].account_id is None


@pytest.mark.asyncio
async def test_ac3_write_helper_sanitizes_long_tool_name(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "g.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        issue = KnownIssue(status="open", category="bug", severity="low", title="t")
        session.add(issue); await session.commit(); await session.refresh(issue)

    overlong = "x" * 500
    async with session_factory() as session:
        await feedback.write_known_issue_match_event(
            session,
            known_issue_id=issue.id,
            related_tool=overlong,
            error_fingerprint_hash=None,
            account_id=None,
            bearer_token_id=None,
            source="injection",
        )
        await session.commit()
    async with session_factory() as session:
        row = (await session.execute(select(KnownIssueMatchEvent))).scalar_one()
    assert row.related_tool is not None
    assert len(row.related_tool) <= 128, "AC #3: related_tool must be sanitized to 128 chars"


# ─── AC #4: augment_tool_error writes injection event ────────────────────────


@pytest.mark.asyncio
async def test_ac4_augment_tool_error_writes_injection_event_on_match(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "ai.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)

    match = feedback.KnownIssueMatch(id=99, status="workaround_available", title="t", playbook={
        "version": 1, "summary": "x", "steps": [], "do_not_do": [],
        "recommended_tool_sequence": [], "safe_to_retry": True,
    })
    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", AsyncMock(return_value=match))
    monkeypatch.setattr(feedback, "write_auto_feedback_event", AsyncMock(return_value=None))
    # Need a real KnownIssue row for FK — even though injected event refs id=99 (no FK enforce on SQLite by default).
    async with session_factory() as session:
        session.add(KnownIssue(id=99, status="workaround_available", category="bug", severity="low", title="t"))
        await session.commit()

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    await feedback.augment_tool_error("get_payments", credentials, ToolError("boom"))

    async with session_factory() as session:
        rows = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert len(rows) == 1, "AC #4: injection event must be written when match exists"
    assert rows[0].source == "injection"
    assert rows[0].known_issue_id == 99
    assert rows[0].account_id == 10
    assert rows[0].bearer_token_id == 20


@pytest.mark.asyncio
async def test_ac4_augment_tool_error_writes_no_event_when_no_match(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "an.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", AsyncMock(return_value=None))
    monkeypatch.setattr(feedback, "write_auto_feedback_event", AsyncMock(return_value=None))

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    await feedback.augment_tool_error("get_payments", credentials, ToolError("boom"))

    async with session_factory() as session:
        rows = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert rows == [], "AC #4: no event when no match"


@pytest.mark.asyncio
async def test_ac7_augment_tool_error_survives_event_write_failure(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper, caplog
) -> None:
    """Caller best-effort: if event write fails, augment_tool_error keeps working."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "asf.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)

    match = feedback.KnownIssueMatch(id=1, status="workaround_available", title="t", playbook={
        "version": 1, "summary": "x", "steps": [], "do_not_do": [],
        "recommended_tool_sequence": [], "safe_to_retry": True,
    })
    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", AsyncMock(return_value=match))
    monkeypatch.setattr(feedback, "write_auto_feedback_event", AsyncMock(return_value=None))
    monkeypatch.setattr(
        feedback,
        "write_known_issue_match_event",
        AsyncMock(side_effect=RuntimeError("simulated DB outage")),
    )

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    result = await feedback.augment_tool_error("get_payments", credentials, ToolError("boom"))
    assert isinstance(result, ToolError), "AC #7: middleware must continue despite event write failure"


# ─── AC #5: write_auto_feedback_event writes event despite dedup ─────────────


@pytest.mark.asyncio
async def test_ac5_write_auto_feedback_event_writes_event_even_if_report_skipped_by_dedup(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "wd.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    feedback._auto_event_stamps.clear()

    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 date filter failed",
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    async with session_factory() as session:
        session.add(KnownIssue(
            status="open", category="bug", severity="medium",
            title="Open match-only", related_tool="get_payments",
            error_fingerprint_hash=fingerprint,
        ))
        await session.commit()

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    # Fire the same auto-event 3 times — second/third skipped by dedup; events must still persist.
    for _ in range(3):
        await feedback.write_auto_feedback_event(
            credentials=credentials,
            tool_name="get_payments",
            exc=ToolError("HTTP 500 date filter failed"),
        )

    async with session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
        reports = (await session.execute(select(AgentFeedbackReport))).scalars().all()

    assert len(events) == 3, "AC #5: every match emits an event, even after report dedup"
    assert all(e.source == "auto" for e in events)
    assert len(reports) == 1, "AC #5: only first auto-report persists due to dedup window"


# ─── AC #6: create_feedback_report writes event atomically with report ───────


@pytest.mark.asyncio
async def test_ac6_create_feedback_report_writes_event_atomic_with_report(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "cr.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        http_status=422,
        error_code="ToolError",
        error_excerpt="HTTP 422 date filter mismatch",
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    playbook = {
        "version": 1, "summary": "x", "steps": ["Retry"],
        "do_not_do": [], "recommended_tool_sequence": ["get_payments"], "safe_to_retry": True,
    }
    rules = {"version": 1, "all": [{"field": "related_tool", "op": "eq", "value": "get_payments"}]}
    async with session_factory() as session:
        session.add(KnownIssue(
            status="workaround_available", category="bug", severity="medium",
            title="workaround", related_tool="get_payments",
            error_fingerprint_hash=fingerprint,
            match_rules_json=json.dumps(rules),
            agent_playbook_json=json.dumps(playbook),
        ))
        await session.commit()

    await feedback.create_feedback_report(
        credentials=credentials,
        category="bug",
        severity="medium",
        summary="HTTP 422",
        details="HTTP 422 for date filter mismatch",
        related_tool="get_payments",
        http_status=422,
        error_code="ToolError",
        error_excerpt="HTTP 422 date filter mismatch",
        params_shape=["date_from", "date_to"],
    )

    async with session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
        reports = (await session.execute(select(AgentFeedbackReport))).scalars().all()
    assert len(events) == 1, "AC #6: report-source event written atomically with the report"
    assert events[0].source == "report"
    assert len(reports) == 1


# ─── AC #8: match-events-cleanup retention ───────────────────────────────────


@pytest.mark.asyncio
async def test_ac8_match_events_cleanup_removes_old_keeps_recent(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "rc.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)

    import scripts.triage_agent_feedback as triage
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    now = feedback._now()
    async with session_factory() as session:
        issue = KnownIssue(status="open", category="bug", severity="low", title="t")
        session.add(issue); await session.commit(); await session.refresh(issue)
        old = KnownIssueMatchEvent(
            known_issue_id=issue.id, source="auto", related_tool="t",
            error_fingerprint_hash=None, account_id=None, bearer_token_id=None,
            created_at=now - timedelta(days=200),
        )
        recent = KnownIssueMatchEvent(
            known_issue_id=issue.id, source="injection", related_tool="t",
            error_fingerprint_hash=None, account_id=None, bearer_token_id=None,
            created_at=now - timedelta(days=10),
        )
        session.add_all([old, recent])
        await session.commit()

    parser = triage._build_parser()
    args = parser.parse_args(["match-events-cleanup", "--days", "90"])
    await args.func(args)

    async with session_factory() as session:
        rows = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert len(rows) == 1
    assert rows[0].source == "injection", "AC #8: only old (>90d) row removed"


# ─── AC #9: match-events-stats output ────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac9_match_events_stats_outputs_table(
    sqlite_session_factory_builder, tmp_path, monkeypatch, feedback_pepper, capsys
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "st.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    import scripts.triage_agent_feedback as triage
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)

    now = feedback._now()
    async with session_factory() as session:
        issue1 = KnownIssue(status="open", category="bug", severity="low", title="Issue One")
        issue2 = KnownIssue(status="open", category="bug", severity="medium", title="Issue Two")
        session.add_all([issue1, issue2])
        await session.commit()
        await session.refresh(issue1); await session.refresh(issue2)

        for _ in range(5):
            session.add(KnownIssueMatchEvent(
                known_issue_id=issue1.id, source="injection", related_tool="t",
                error_fingerprint_hash=None, account_id=10, bearer_token_id=20,
                created_at=now - timedelta(hours=1),
            ))
        for _ in range(2):
            session.add(KnownIssueMatchEvent(
                known_issue_id=issue2.id, source="auto", related_tool="t",
                error_fingerprint_hash=None, account_id=None, bearer_token_id=21,
                created_at=now - timedelta(hours=1),
            ))
        await session.commit()

    parser = triage._build_parser()
    args = parser.parse_args(["match-events-stats", "--days", "7", "--top", "10"])
    await args.func(args)
    out = capsys.readouterr().out
    assert "Issue One" in out
    assert "Issue Two" in out
    assert "injection" in out
    assert "auto" in out
    # Check that issue1 (5 events) appears before issue2 (2 events) — events DESC ordering.
    assert out.index("Issue One") < out.index("Issue Two")
