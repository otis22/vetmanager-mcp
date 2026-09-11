"""Stage 312: known-issue tool names must be truthful where they are search keys."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

import agent_feedback_service as feedback
import scripts.triage_agent_feedback as triage
from storage_models import Account, AgentFeedbackReport, KnownIssue, ServiceBearerToken
from tests.runtime_factories import make_runtime_credentials


REPO_ROOT = Path(__file__).resolve().parent.parent


def _rules_for_tools(*tools: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "all": [
                {"field": "related_tool", "op": "in", "value": list(tools)},
                {"field": "normalized_error_text", "op": "contains_any", "value": ["export"]},
            ],
        },
        ensure_ascii=False,
    )


def _playbook() -> str:
    return json.dumps(
        {
            "version": 1,
            "summary": "Use the export workaround.",
            "steps": ["Retry through export."],
            "do_not_do": ["Do not poll forever."],
            "recommended_tool_sequence": ["get_report_export_download"],
            "safe_to_retry": True,
        },
        ensure_ascii=False,
    )


def _report(**overrides) -> AgentFeedbackReport:
    data = {
        "source": "model",
        "category": "bug",
        "severity": "medium",
        "status": "new",
        "related_tool": "Vetmanager task area",
        "summary": "Free-form tool name leaked into feedback.",
        "details": "Shape-only report.",
        "error_fingerprint_hash": "hmac-sha256:stage312",
        "possible_pii": False,
    }
    data.update(overrides)
    return AgentFeedbackReport(**data)


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage312-pepper")


@pytest.mark.asyncio
async def test_auto_feedback_with_known_issue_is_linked_not_new(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch, feedback_pepper
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "auto-linked.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    feedback._auto_event_stamps.clear()
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    incident = feedback.FeedbackIncident(
        related_tool="get_report_export_download",
        error_code="ToolError",
        error_excerpt="export failed",
    )
    async with session_factory() as session:
        session.add(
            KnownIssue(
                status="acknowledged",
                category="bug",
                severity="medium",
                title="Export failure",
                related_tool="get_report_export_download",
                error_fingerprint_hash=feedback.build_error_fingerprint_hash(incident),
            )
        )
        await session.commit()

    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_report_export_download",
        exc=ToolError("export failed"),
    )

    async with session_factory() as session:
        report = (await session.execute(select(AgentFeedbackReport))).scalar_one()
    assert report.known_issue_id is not None
    assert report.status == feedback.FEEDBACK_STATUS_LINKED
    assert report.status != feedback.FEEDBACK_STATUS_NEW


def test_match_rules_reject_unknown_related_tool_names() -> None:
    assert feedback.validate_match_rules_json(_rules_for_tools("get_clients"), strict_tool_names=True) is not None
    assert feedback.validate_match_rules_json(_rules_for_tools("tool_that_does_not_exist"), strict_tool_names=True) is None
    assert (
        feedback.validate_match_rules_json(
            json.dumps(
                {
                    "version": 1,
                    "all": [
                        {
                            "field": "related_tool",
                            "op": "eq",
                            "value": "tool_that_does_not_exist",
                        }
                    ],
                }
            ),
            strict_tool_names=True,
        )
        is None
    )


def test_runtime_match_rules_keep_valid_tool_when_a_stale_name_is_present() -> None:
    assert feedback.match_rules(
        _rules_for_tools("get_report_export_download", "get_report_export_file"),
        feedback.FeedbackIncident(
            related_tool="get_report_export_download",
            error_code="ToolError",
            error_excerpt="export failed",
        ),
    )


def test_null_related_tool_without_rules_does_not_match_every_failure() -> None:
    assert not feedback.match_rules(
        None,
        feedback.FeedbackIncident(
            related_tool="get_report_export_download",
            error_code="ToolError",
            error_excerpt="export failed",
        ),
    )


def test_seed_tool_name_gate_checks_related_tool_and_rules(tmp_path: Path) -> None:
    script = REPO_ROOT / "scripts" / "check_known_issue_tool_names.py"
    assert script.exists()

    good = subprocess.run(
        [sys.executable, str(script)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert good.returncode == 0, good.stderr

    poisoned = tmp_path / "poisoned_seed.py"
    poisoned.write_text(
        """
from dataclasses import dataclass

@dataclass(frozen=True)
class SeedIssue:
    slug: str
    related_tool: str | None
    match_rules: dict

SEED_ISSUES = (
    SeedIssue(
        slug="bad-field",
        related_tool="tool_that_does_not_exist",
        match_rules={"version": 1, "all": []},
    ),
    SeedIssue(
        slug="bad-rule",
        related_tool="get_clients",
        match_rules={
            "version": 1,
            "all": [
                {
                    "field": "related_tool",
                    "op": "in",
                    "value": ["get_clients", "tool_that_does_not_exist"],
                }
            ],
        },
    ),
    SeedIssue(
        slug="unparsed-rule",
        related_tool="get_clients",
        match_rules=custom_rules("tool_that_does_not_exist"),
    ),
    SeedIssue(
        slug="unparsed-field",
        related_tool=choose_tool(),
        match_rules={"version": 1, "all": []},
    ),
)
""",
        encoding="utf-8",
    )

    bad = subprocess.run(
        [sys.executable, str(script), "--seed-module-path", str(poisoned)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert bad.returncode != 0
    assert "[seed:bad-field] related_tool 'tool_that_does_not_exist'" in bad.stderr
    assert "[seed:bad-rule] match_rules related_tool 'tool_that_does_not_exist'" in bad.stderr
    assert "[seed:unparsed-rule] match_rules could not be parsed" in bad.stderr
    assert "[seed:unparsed-field] related_tool could not be parsed" in bad.stderr

    missing = tmp_path / "missing_seed.py"
    missing.write_text("SEED_ISSUES = tuple()\n", encoding="utf-8")
    missing_result = subprocess.run(
        [sys.executable, str(script), "--seed-module-path", str(missing)],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert missing_result.returncode != 0
    assert "[seed:<module>] match_rules could not be parsed" in missing_result.stderr


@pytest.mark.asyncio
async def test_diagnostic_seed_issue_does_not_store_fake_related_tool(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch, feedback_pepper
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "diagnostic-seed.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        account = Account(email="stage312@example.com", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(
            account_id=account.id,
            name="stage312",
            token_prefix="sbt_stage312",
            token_hash="stage312_hash_" + "x" * 48,
            status="active",
        )
        session.add(token)
        await session.commit()
        await session.refresh(account)
        await session.refresh(token)

    result = await seed.diagnostic_auto_event(
        apply=True,
        account_id=account.id,
        bearer_token_id=token.id,
        run_id="rid-abcd-efab",
    )

    async with session_factory() as session:
        issue = (
            await session.execute(select(KnownIssue).where(KnownIssue.title == seed.DIAGNOSTIC_TITLE))
        ).scalar_one()

    assert result["status"] == "ok"
    assert issue.related_tool is None
    rules = json.loads(issue.match_rules_json or "{}")
    assert all(condition.get("field") != "related_tool" for condition in rules.get("all", []))


@pytest.mark.asyncio
async def test_promote_rejects_free_form_related_tool_without_override(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "promote-rejects.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        session.add(_report())
        await session.commit()
        report_id = (await session.execute(select(AgentFeedbackReport.id))).scalar_one()

    with pytest.raises(SystemExit, match="Unknown related_tool"):
        await triage._promote(
            SimpleNamespace(
                report_id=report_id,
                title="",
                status="acknowledged",
                public_summary=None,
                workaround=None,
                playbook_json=None,
                match_rules_json=None,
                related_tool=None,
            )
        )

    async with session_factory() as session:
        assert (await session.execute(select(KnownIssue))).scalars().all() == []


@pytest.mark.asyncio
async def test_promote_allows_registered_or_empty_related_tool_override(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "promote-override.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        session.add(_report())
        session.add(_report(summary="Second report"))
        await session.commit()
        report_ids = (await session.execute(select(AgentFeedbackReport.id).order_by(AgentFeedbackReport.id))).scalars().all()

    await triage._promote(
        SimpleNamespace(
            report_id=report_ids[0],
            title="",
            status="acknowledged",
            public_summary=None,
            workaround=None,
            playbook_json=None,
            match_rules_json=None,
            related_tool="get_report_export_download",
        )
    )
    await triage._promote(
        SimpleNamespace(
            report_id=report_ids[1],
            title="",
            status="acknowledged",
            public_summary=None,
            workaround=None,
            playbook_json=None,
            match_rules_json=None,
            related_tool="",
        )
    )

    async with session_factory() as session:
        issues = (await session.execute(select(KnownIssue).order_by(KnownIssue.id))).scalars().all()
    assert issues[0].related_tool == "get_report_export_download"
    assert issues[1].related_tool is None


@pytest.mark.asyncio
async def test_set_related_tool_updates_and_rejects_unknown(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "set-related-tool.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Known issue",
            related_tool="get_clients",
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)
        issue_id = issue.id

    await triage._set_related_tool(SimpleNamespace(known_issue_id=issue_id, related_tool=""))
    async with session_factory() as session:
        assert (await session.get(KnownIssue, issue_id)).related_tool is None

    with pytest.raises(SystemExit, match="Unknown related_tool"):
        await triage._set_related_tool(
            SimpleNamespace(known_issue_id=issue_id, related_tool="tool_that_does_not_exist")
        )


@pytest.mark.asyncio
async def test_set_match_rules_rejects_unknown_related_tool_name(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "set-rules-rejects.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Known issue",
            related_tool=None,
        )
        session.add(issue)
        await session.commit()
        await session.refresh(issue)
        issue_id = issue.id

    rules = tmp_path / "rules.json"
    rules.write_text(_rules_for_tools("tool_that_does_not_exist"), encoding="utf-8")

    with pytest.raises(SystemExit, match="Invalid match rules JSON"):
        await triage._set_match_rules(SimpleNamespace(known_issue_id=issue_id, match_rules_json=str(rules)))

    async with session_factory() as session:
        assert (await session.get(KnownIssue, issue_id)).match_rules_json is None


@pytest.mark.asyncio
async def test_unreachable_issues_names_unknown_related_tool_reason(
    sqlite_session_factory_builder, tmp_path: Path, monkeypatch, capsys
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "unreachable-tool.db")
    monkeypatch.setattr(triage, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        session.add_all(
            [
                KnownIssue(
                    status="acknowledged",
                    category="bug",
                    severity="high",
                    title="Bad tool",
                    related_tool="tool_that_does_not_exist",
                    agent_playbook_json=_playbook(),
                ),
                KnownIssue(
                    status="acknowledged",
                    category="bug",
                    severity="medium",
                    title="Null tool",
                    related_tool=None,
                    agent_playbook_json=_playbook(),
                ),
                KnownIssue(
                    status="acknowledged",
                    category="bug",
                    severity="low",
                    title="Valid tool",
                    related_tool="get_clients",
                    agent_playbook_json=_playbook(),
                ),
                KnownIssue(
                    status="acknowledged",
                    category="bug",
                    severity="medium",
                    title="Bad rule tool",
                    related_tool=None,
                    match_rules_json=_rules_for_tools("tool_that_does_not_exist"),
                    agent_playbook_json=_playbook(),
                ),
            ]
        )
        await session.commit()

    await triage._unreachable_issues(SimpleNamespace())
    out = capsys.readouterr().out

    assert "unknown related_tool" in out
    assert "invalid match_rules" in out
    assert "tool_that_does_not_exist" in out
    assert "total=2" in out
    assert "Null tool" not in out
    assert "Valid tool" not in out
