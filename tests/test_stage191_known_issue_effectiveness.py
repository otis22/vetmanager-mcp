"""Stage 191 known-issue match effectiveness diagnostics."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import select

import agent_feedback_service as feedback
import scripts.triage_agent_feedback as triage_cli
from storage_models import AgentFeedbackReport, KnownIssue, KnownIssueMatchEvent
from tests.runtime_factories import make_runtime_credentials

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage191-feedback-pepper")


def _playbook() -> dict:
    return {
        "version": 1,
        "summary": "Retry with an explicit date range.",
        "steps": ["Call get_payments with date_from and date_to."],
        "do_not_do": ["Do not retry without date filters."],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }


def _rules() -> dict:
    return {
        "version": 1,
        "all": [
            {"field": "related_tool", "op": "eq", "value": "get_payments"},
            {"field": "normalized_error_text", "op": "contains_any", "value": ["date filter"]},
        ],
    }


def test_stage191_cli_file_runs_without_pythonpath() -> None:
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [sys.executable, "scripts/triage_agent_feedback.py", "--help"],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "match-effectiveness" in result.stdout


@pytest.mark.asyncio
async def test_stage191_injection_match_writes_event_and_playbook(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage191-injection.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    async with session_factory() as session:
        session.add(KnownIssue(
            status="workaround_available",
            category="bug",
            severity="medium",
            title="Date filter workaround",
            related_tool="get_payments",
            match_rules_json=json.dumps(_rules()),
            agent_playbook_json=json.dumps(_playbook()),
        ))
        await session.commit()

    augmented = await feedback.augment_tool_error(
        "get_payments",
        credentials,
        ToolError("HTTP 500 date filter failed"),
    )

    assert "Known issue playbook" in str(augmented)
    async with session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()

    assert {event.source for event in events} >= {"injection"}
    injection = next(event for event in events if event.source == "injection")
    assert injection.related_tool == "get_payments"
    assert injection.account_id == 10
    assert injection.bearer_token_id == 20


@pytest.mark.asyncio
async def test_stage191_no_match_writes_no_false_event(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage191-no-match.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    augmented = await feedback.augment_tool_error(
        "get_payments",
        credentials,
        ToolError("HTTP 500 unrelated failure"),
    )

    assert "Known issue playbook" not in str(augmented)
    async with session_factory() as session:
        events = (await session.execute(select(KnownIssueMatchEvent))).scalars().all()
    assert events == []


@pytest.mark.asyncio
async def test_stage191_match_effectiveness_cli_is_aggregate_only(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    capsys,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage191-cli.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        issue = KnownIssue(
            status="workaround_available",
            category="bug",
            severity="medium",
            title="Do not print alice@example.com",
            related_tool="get_payments",
            match_rules_json=json.dumps(_rules()),
            agent_playbook_json=json.dumps(_playbook()),
        )
        skipped_issue = KnownIssue(
            status="workaround_available",
            category="bug",
            severity="medium",
            title="Missing playbook should be aggregate only",
            related_tool="get_clients",
            match_rules_json=json.dumps(_rules()),
        )
        session.add_all([issue, skipped_issue])
        await session.flush()
        session.add_all([
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="medium",
                status="linked",
                related_tool="get_payments",
                summary="Raw summary alice@example.com must not print",
                details="Raw details +7 999 123-45-67 must not print",
                known_issue_id=issue.id,
            ),
            AgentFeedbackReport(
                source="auto",
                category="bug",
                severity="low",
                status="new",
                related_tool="get_clients",
                summary="No match raw summary must not print",
                details="No match raw details must not print",
            ),
            KnownIssueMatchEvent(
                known_issue_id=issue.id,
                related_tool="get_payments",
                source="injection",
            ),
        ])
        await session.commit()

    await triage_cli._match_effectiveness(SimpleNamespace(days=30))

    output = capsys.readouterr().out
    assert "Reports by source/status" in output
    assert "Match events by source" in output
    assert "Known issue readiness" in output
    assert "| model | linked | 1 | 1 | 0 |" in output
    assert "| auto | new | 1 | 0 | 1 |" in output
    assert "| injection | 1 |" in output
    assert "agent_injection_skipped" in output
    assert "alice@example.com" not in output
    assert "+7 999" not in output
    assert "Raw summary" not in output
    assert "Do not print" not in output
