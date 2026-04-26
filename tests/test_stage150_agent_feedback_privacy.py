"""Stage 150 privacy guardrails for agent feedback."""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace

from fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import select

import agent_feedback_service as feedback
import scripts.triage_agent_feedback as triage_cli
from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS
from tools.feedback import register as register_feedback_tools
from storage_models import AgentFeedbackReport, KnownIssue
from tests.runtime_factories import make_runtime_credentials


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "test-feedback-pepper")


def test_feedback_sanitizer_redacts_contextual_pii_and_keeps_domain_language():
    text = (
        "клиент Иванов И.И.; owner: John Smith; кличка Барсик; "
        "адрес: Москва, Ленина 1; email test@example.com; phone +7 999 123-45-67"
    )

    result = feedback.sanitize_text_with_metadata(text, limit=1000)

    assert result.text is not None
    assert "Иванов" not in result.text
    assert "John Smith" not in result.text
    assert "Барсик" not in result.text
    assert "Москва" not in result.text
    assert "test@example.com" not in result.text
    assert "+7 999" not in result.text
    assert {
        "contextual_name",
        "contextual_patient",
        "contextual_address",
        "email",
        "phone",
    }.issubset(result.redactions)

    harmless = feedback.sanitize_text_with_metadata(
        "client search returns 500; patient endpoint contract mismatch; ошибка поиска клиента; "
        "request id 123456789012 id 8001234567 trace 12-34-56-78-90 "
        "version 2026-04-26T10:20:30",
        limit=1000,
    )
    assert harmless.text == (
        "client search returns 500; patient endpoint contract mismatch; ошибка поиска клиента; "
        "request id 123456789012 id 8001234567 trace 12-34-56-78-90 "
        "version 2026-04-26T10:20:30"
    )
    assert feedback.PRIVACY_REDACTIONS.isdisjoint(harmless.redactions)

    capitalized = feedback.sanitize_text_with_metadata("Client: John Smith; PATIENT Барсик", limit=1000)
    assert "John Smith" not in (capitalized.text or "")
    assert "Барсик" not in (capitalized.text or "")
    assert {"contextual_name", "contextual_patient"}.issubset(capitalized.redactions)


def test_feedback_sanitizer_exception_fails_closed(monkeypatch):
    class BrokenPattern:
        def search(self, value):
            raise RuntimeError("regex failed")

    monkeypatch.setattr(feedback, "_EMAIL_RE", BrokenPattern())

    result = feedback.sanitize_text_with_metadata("client Иванов И.И.", limit=1000)

    assert result.text == "[REDACTED]"
    assert "sanitizer_error" in result.redactions


def test_report_problem_instructions_describe_shape_not_data():
    description = SPECIAL_TOOL_DESCRIPTIONS["report_problem"]
    server_source = (Path(__file__).resolve().parents[1] / "server.py").read_text(encoding="utf-8")
    feedback_source = inspect.getsource(register_feedback_tools)

    assert "<client>" in server_source
    assert "<owner>" in description
    assert "Describe the shape of the problem, not the data" in description
    assert "client <client> lookup returns 500" in feedback_source
    assert "<patient>" in feedback_source


@pytest.mark.asyncio
async def test_report_problem_persists_redacted_text_and_possible_pii_flag(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage150-feedback.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    result = await feedback.create_feedback_report(
        credentials=credentials,
        category="bug",
        severity="medium",
        summary="client <client> payment bug",
        details="клиент Иванов И.И. phone +7 999 123-45-67 triggers 500",
        error_excerpt="request id 123456789012 version 2026-04-26T10:20:30",
    )

    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, result["feedback_id"])

    assert report is not None
    assert report.possible_pii is True
    assert "Иванов" not in report.details
    assert "+7 999" not in report.details
    assert report.error_fingerprint_hash is not None

    clean = await feedback.create_feedback_report(
        credentials=credentials,
        category="bug",
        severity="low",
        summary="client search returns 500",
        details="ошибка поиска клиента без персональных данных",
    )
    async with session_factory() as session:
        clean_report = await session.get(AgentFeedbackReport, clean["feedback_id"])

    assert clean_report is not None
    assert clean_report.possible_pii is False


@pytest.mark.asyncio
async def test_auto_event_possible_pii_false_and_triage_outputs_flag(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    capsys,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage150-triage.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 date filter failed",
    )
    async with session_factory() as session:
        session.add(KnownIssue(
            status="open",
            category="bug",
            severity="medium",
            title="Matched issue",
            related_tool="get_payments",
            error_fingerprint_hash=feedback.build_error_fingerprint_hash(incident),
        ))
        await session.commit()

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("HTTP 500 date filter failed"),
    )

    async with session_factory() as session:
        report = (await session.execute(select(AgentFeedbackReport))).scalar_one()

    assert report.possible_pii is False

    await triage_cli._recent(SimpleNamespace(limit=10))
    recent_output = capsys.readouterr().out
    assert "possible_pii=false" in recent_output

    await triage_cli._export(SimpleNamespace(limit=10))
    export_output = capsys.readouterr().out
    assert "- possible_pii: false" in export_output
