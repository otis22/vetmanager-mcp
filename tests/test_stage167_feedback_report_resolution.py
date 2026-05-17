"""Stage 167: feedback report fixed-resolution CLI."""

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
        "severity": "medium",
        "status": "new",
        "related_tool": "vetmanager__get_invoice_documents",
        "summary": "Invoice documents fail",
        "details": "Shape-only feedback without raw customer data.",
        "error_fingerprint_hash": "hmac-sha256:stage167",
        "possible_pii": False,
    }
    data.update(overrides)
    return AgentFeedbackReport(**data)


@pytest.mark.asyncio
async def test_resolve_report_creates_fixed_known_issue_and_links_report(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage167-create.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        report = _report()
        session.add(report)
        await session.commit()
        await session.refresh(report)
        report_id = report.id

    await triage_cli._resolve_report(SimpleNamespace(
        report_id=report_id,
        status="fixed",
        title="client Иванов fixed by Stage 161",
        public_summary="client Иванов fixed by Stage 161: invoice_id is converted to document_id internally.",
        workaround="Use get_invoice_documents(invoice_id=<invoice_id>); no document_id input is needed.",
    ))

    output = capsys.readouterr().out
    assert f"report #{report_id} linked known_issue #" in output
    assert "status=fixed" in output

    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, report_id)
        issue = (await session.execute(select(KnownIssue))).scalar_one()

    assert report is not None
    assert report.status == "linked"
    assert report.known_issue_id == issue.id
    assert issue.status == "fixed"
    assert "Иванов" not in issue.title
    assert issue.related_tool == "vetmanager__get_invoice_documents"
    assert issue.error_fingerprint_hash == "hmac-sha256:stage167"
    assert "Иванов" not in (issue.public_summary or "")
    assert "invoice_id is converted to document_id internally" in (issue.public_summary or "")


@pytest.mark.asyncio
async def test_resolve_report_updates_existing_known_issue_and_recent_shows_fixed(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage167-update.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        issue = KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Curated title",
            related_tool="vetmanager__get_invoice_documents",
            error_fingerprint_hash="hmac-sha256:stage167",
            public_summary="Curated operator summary",
            workaround="Curated workaround",
        )
        session.add(issue)
        await session.flush()
        report = _report(status="linked", known_issue_id=issue.id)
        session.add(report)
        await session.commit()
        await session.refresh(report)
        report_id = report.id

    await triage_cli._resolve_report(SimpleNamespace(
        report_id=report_id,
        status="fixed",
        title="",
        public_summary="",
        workaround="",
    ))

    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, report_id)
        issue = await session.get(KnownIssue, report.known_issue_id)

    assert issue is not None
    assert issue.status == "fixed"
    assert issue.title == "Curated title"
    assert issue.public_summary == "Curated operator summary"
    assert issue.workaround == "Curated workaround"

    await triage_cli._recent(SimpleNamespace(limit=10))
    recent_output = capsys.readouterr().out
    assert f"#{report_id} [linked]" in recent_output
    assert f"known_issue=#{issue.id}/fixed" in recent_output


@pytest.mark.asyncio
async def test_resolve_report_rejects_invalid_status_before_commit(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage167-invalid.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        report = _report()
        session.add(report)
        await session.commit()
        await session.refresh(report)
        report_id = report.id

    with pytest.raises(SystemExit, match="Invalid known issue status"):
        await triage_cli._resolve_report(SimpleNamespace(
            report_id=report_id,
            status="done",
            title="Bad status",
            public_summary=None,
            workaround=None,
        ))

    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, report_id)
        issues = (await session.execute(select(KnownIssue))).scalars().all()

    assert report is not None
    assert report.status == "new"
    assert report.known_issue_id is None
    assert issues == []
