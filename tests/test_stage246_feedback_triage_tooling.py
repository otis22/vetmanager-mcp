"""Stage 246: show / redact / link subcommands of the feedback triage CLI."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

import scripts.triage_agent_feedback as triage_cli
from storage_models import AgentFeedbackReport, KnownIssue


def _report(**overrides) -> AgentFeedbackReport:
    data = {
        "source": "model",
        "category": "bug",
        "severity": "high",
        "status": "new",
        "related_tool": "vetmanager__update_medical_card",
        "summary": "update_medical_card rejects an existing card",
        "details": "Shape-only feedback without raw customer data.",
        "reproduce": "Call the tool with a card id that reads fine.",
        "suggested_fix": "Send patient_id together with the changed fields.",
        "error_fingerprint_hash": "hmac-sha256:stage246",
        "possible_pii": False,
    }
    data.update(overrides)
    return AgentFeedbackReport(**data)


async def _seed(session_factory, report: AgentFeedbackReport) -> int:
    async with session_factory() as session:
        session.add(report)
        await session.commit()
        await session.refresh(report)
        return report.id


@pytest.mark.asyncio
async def test_show_prints_body_fields_not_only_summary(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-show.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    report_id = await _seed(session_factory, _report())

    await triage_cli._show(SimpleNamespace(report_ids=[report_id, report_id + 999]))

    output = capsys.readouterr().out
    assert "Shape-only feedback without raw customer data." in output
    assert "Call the tool with a card id that reads fine." in output
    assert "Send patient_id together with the changed fields." in output
    assert f"#{report_id + 999}: not found" in output


@pytest.mark.asyncio
async def test_redact_rewrites_text_and_recomputes_possible_pii(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-redact.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    # Stored before the sanitizer learned this pattern: a row can carry text the
    # current patterns would strip, while possible_pii still says false.
    report_id = await _seed(session_factory, _report(
        details="Owner reported it. client: Иванов asked twice.",
        possible_pii=False,
    ))

    await triage_cli._redact(SimpleNamespace(report_ids=[report_id], dry_run=False))

    assert "possible_pii=true" in capsys.readouterr().out
    async with session_factory() as session:
        stored = await session.get(AgentFeedbackReport, report_id)
        assert "Иванов" not in stored.details
        assert "[REDACTED]" in stored.details
        assert stored.possible_pii is True
        assert stored.redaction_version == triage_cli.REDACTION_VERSION


@pytest.mark.asyncio
async def test_redact_dry_run_leaves_the_row_untouched(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-dry.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    report_id = await _seed(session_factory, _report(details="client: Иванов asked twice."))

    await triage_cli._redact(SimpleNamespace(report_ids=[report_id], dry_run=True))

    assert "would update" in capsys.readouterr().out
    async with session_factory() as session:
        stored = await session.get(AgentFeedbackReport, report_id)
        assert "Иванов" in stored.details


@pytest.mark.asyncio
async def test_link_attaches_several_reports_to_one_known_issue(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-link.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    first = await _seed(session_factory, _report(error_fingerprint_hash="hmac-sha256:a"))
    second = await _seed(session_factory, _report(error_fingerprint_hash="hmac-sha256:b"))

    await triage_cli._promote(SimpleNamespace(
        report_id=first,
        title="update_medical_card rejects existing cards",
        status="acknowledged",
        public_summary=None,
        workaround=None,
        playbook_json=None,
        match_rules_json=None,
    ))
    async with session_factory() as session:
        issue_id = (await session.execute(select(KnownIssue))).scalar_one().id

    # The same bug arrives under a second fingerprint; it must join the existing
    # issue instead of creating a rival one.
    await triage_cli._link(SimpleNamespace(known_issue_id=issue_id, report_ids=[second]))

    assert f"linked report #{second} to known_issue #{issue_id}" in capsys.readouterr().out
    async with session_factory() as session:
        assert len((await session.execute(select(KnownIssue))).scalars().all()) == 1
        stored = await session.get(AgentFeedbackReport, second)
        assert stored.known_issue_id == issue_id
        assert stored.status == triage_cli.FEEDBACK_STATUS_LINKED


@pytest.mark.asyncio
async def test_link_rejects_an_unknown_issue(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-missing.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    report_id = await _seed(session_factory, _report())

    with pytest.raises(SystemExit):
        await triage_cli._link(SimpleNamespace(known_issue_id=4242, report_ids=[report_id]))


@pytest.mark.asyncio
async def test_link_is_idempotent_for_duplicate_and_already_linked_report(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-idempotent.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    report_id = await _seed(session_factory, _report())
    await triage_cli._promote(SimpleNamespace(
        report_id=report_id, title="existing", status="acknowledged",
        public_summary=None, workaround=None, playbook_json=None, match_rules_json=None,
    ))
    async with session_factory() as session:
        issue = (await session.execute(select(KnownIssue))).scalar_one()
        issue_id = issue.id

    await triage_cli._link(SimpleNamespace(known_issue_id=issue_id, report_ids=[report_id, report_id]))

    assert capsys.readouterr().out.count("already linked") == 2
    async with session_factory() as session:
        issue = await session.get(KnownIssue, issue_id)
        assert issue.report_count == 1


@pytest.mark.asyncio
async def test_redact_skips_a_row_that_would_lose_a_required_field(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys,
) -> None:
    """A sharper sanitizer can swallow a whole required field.

    Control characters are the one input the current sanitizer reduces to
    nothing; a future rule that deletes rather than masks would do the same to
    ordinary text. Either way the batch must survive: report the row, leave it
    alone, keep going.
    """
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage246-empty.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    first = await _seed(session_factory, _report(details="\x01\x02\x03"))
    second = await _seed(session_factory, _report(details="Plain shape-only text."))

    await triage_cli._redact(SimpleNamespace(report_ids=[first, second], dry_run=False))

    output = capsys.readouterr().out
    assert f"#{first}: SKIPPED, would empty required ['details']" in output
    assert f"#{second}: updated" in output
    async with session_factory() as session:
        untouched = await session.get(AgentFeedbackReport, first)
        assert untouched.details == "\x01\x02\x03"
