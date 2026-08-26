"""Stage 261: an issue nobody can deliver must be visible as such.

Four issues sat in `acknowledged` holding a written answer that the agent was
never allowed to receive, and the readiness table counted a skipped injection
only for `workaround_available` — so the gap did not show up anywhere.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import scripts.triage_agent_feedback as triage_cli
from storage_models import AgentFeedbackReport, KnownIssue


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage261-feedback-pepper")


def _rules() -> dict:
    return {
        "version": 1,
        "all": [{"field": "related_tool", "op": "eq", "value": "get_payments"}],
    }


def _playbook() -> dict:
    return {
        "version": 1,
        "summary": "Use date filters.",
        "steps": ["Retry with date_from and date_to."],
        "do_not_do": [],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }


@pytest.mark.asyncio
async def test_readiness_counts_skipped_injection_for_every_active_status(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys, feedback_pepper
):
    """A missing playbook hides the issue from the agent whatever its status."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage261-readiness.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        session.add_all([
            KnownIssue(
                status="acknowledged",
                category="bug",
                severity="high",
                title="Acknowledged without an answer",
                related_tool="get_payments",
                match_rules_json=json.dumps(_rules()),
            ),
            KnownIssue(
                status="open",
                category="bug",
                severity="medium",
                title="Open without an answer",
                related_tool="get_payments",
                match_rules_json=json.dumps(_rules()),
            ),
        ])
        await session.commit()

    await triage_cli._match_effectiveness(SimpleNamespace(days=30))
    output = capsys.readouterr().out

    assert "| acknowledged | 1 | 1 | 0 | 1 |" in output
    assert "| open | 1 | 1 | 0 | 1 |" in output


@pytest.mark.asyncio
async def test_unreachable_command_names_the_issues_agents_never_see(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys, feedback_pepper
):
    """The point is to act on them, so the report names ids and counts, not totals."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage261-unreachable.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        silent = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="high",
            title="Reported four times, answer never written",
            related_tool="update_medical_card",
            match_rules_json=json.dumps(_rules()),
        )
        answered = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Has an answer, reaches the agent",
            related_tool="get_payments",
            match_rules_json=json.dumps(_rules()),
            agent_playbook_json=json.dumps(_playbook()),
        )
        closed = KnownIssue(
            status="fixed",
            category="bug",
            severity="medium",
            title="Fixed, nothing to work around",
            related_tool="get_clients",
            match_rules_json=json.dumps(_rules()),
        )
        session.add_all([silent, answered, closed])
        await session.flush()
        session.add_all([
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="high",
                status="linked",
                related_tool="update_medical_card",
                summary="Raw summary must not print",
                details="Raw details must not print",
                known_issue_id=silent.id,
            ),
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="high",
                status="linked",
                related_tool="update_medical_card",
                summary="Second raw summary must not print",
                details="Second raw details must not print",
                known_issue_id=silent.id,
            ),
        ])
        await session.commit()
        silent_id, answered_id, closed_id = silent.id, answered.id, closed.id

    await triage_cli._unreachable_issues(SimpleNamespace())
    output = capsys.readouterr().out

    # Match whole rows: an id and a report count look the same inside "| n |".
    listed_ids = [
        int(line.split("|")[1].strip())
        for line in output.splitlines()
        if line.startswith("| ") and line.split("|")[1].strip().isdigit()
    ]
    assert listed_ids == [silent_id]
    assert answered_id not in listed_ids, "an issue with a playbook is reachable"
    assert closed_id not in listed_ids, "a fixed issue needs no workaround"

    # The report is about how many people already hit it, so the count matters.
    silent_row = next(line for line in output.splitlines() if line.startswith(f"| {silent_id} |"))
    assert silent_row.split("|")[5].strip() == "2"
    assert "update_medical_card" in silent_row
    assert "total=1" in output

    # Aggregate-only, like every other triage report: no raw report text.
    assert "Raw summary" not in output
    assert "Raw details" not in output


def test_runbook_only_shows_commands_the_cli_actually_accepts():
    """The runbook is the operational contract — a wrong flag makes it useless.

    The first version of it was written from memory and every id-taking command
    had the wrong signature.
    """
    import re
    import shlex
    from pathlib import Path

    runbook = Path(__file__).resolve().parents[1] / "artifacts" / "feedback-triage-runbook.md"
    parser = triage_cli._build_parser()

    commands = [
        line.strip()
        for line in runbook.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith("python3 scripts/triage_agent_feedback.py")
    ]
    assert commands, "the runbook must show how to run the triage tool"

    for command in commands:
        argv = shlex.split(re.sub(r'"[^"]*"', '"x"', command))[2:]
        parser.parse_args(argv)


@pytest.mark.asyncio
async def test_unreachable_report_survives_an_empty_result_and_a_missing_tool(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys, feedback_pepper
):
    """Nothing unreachable is the goal state, and it must print as such."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage261-empty.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)

    await triage_cli._unreachable_issues(SimpleNamespace())
    assert "total=0" in capsys.readouterr().out

    async with session_factory() as session:
        session.add(KnownIssue(
            status="open",
            category="bug",
            severity="low",
            title="No tool attached",
            match_rules_json=json.dumps(_rules()),
        ))
        await session.commit()

    await triage_cli._unreachable_issues(SimpleNamespace())
    output = capsys.readouterr().out
    assert "total=1" in output
    assert "| - |" in output, "a missing related_tool prints as a dash, not a crash"
