"""Stage 149 agent feedback loop coverage."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastmcp.exceptions import ToolError
import pytest
from sqlalchemy import select

import agent_feedback_service as feedback
from storage_models import AgentFeedbackReport, KnownIssue
from tests.runtime_factories import make_runtime_credentials
import tools
import scripts.triage_agent_feedback as triage_cli


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "test-feedback-pepper")


@pytest.mark.asyncio
async def test_report_problem_sanitizes_and_persists_structured_feedback(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "feedback.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=None, bearer_token_id=None)

    result = await feedback.create_feedback_report(
        credentials=credentials,
        category="bug",
        severity="medium",
        summary="Payment error for user test@example.com",
        details="Authorization: Bearer abcdef1234567890 and phone +7 999 123-45-67 leaked",
        related_tool="get_payments",
        http_status=422,
        error_code="HTTPError",
        error_excerpt="HTTP 422 for client_id 123456 on 2026-04-25",
        params_shape=["date_from", "date_to", "client_id"],
    )

    assert result["ok"] is True
    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, result["feedback_id"])

    assert report is not None
    assert "test@example.com" not in report.summary
    assert "abcdef1234567890" not in report.details
    assert "+7 999" not in report.details
    assert report.error_fingerprint_hash.startswith("hmac-sha256:")
    assert json.loads(report.params_shape_json or "[]") == ["client_id", "date_from", "date_to"]


def test_report_problem_and_wrapper_fingerprint_paths_converge(feedback_pepper):
    report_incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        http_status=422,
        error_code="ToolError",
        error_excerpt="HTTP 422 for client_id 123456 on 2026-04-25",
        params_shape=["date_to", "date_from"],
    )
    wrapper_incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        http_status=422,
        error_code="ToolError",
        error_excerpt="HTTP 422 for client_id 999999 on 2026-04-26",
        params_shape=["date_from", "date_to"],
    )

    assert feedback.build_error_fingerprint_hash(report_incident) == feedback.build_error_fingerprint_hash(
        wrapper_incident
    )


def test_feedback_redaction_covers_bare_token_shapes():
    text = feedback.sanitize_text(
        "jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
        "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c "
        "hex 0123456789abcdef0123456789abcdef "
        "b64 QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo0123456789abcd",
        limit=1000,
    )

    assert text is not None
    assert "eyJhbGci" not in text
    assert "0123456789abcdef0123456789abcdef" not in text
    assert "QUJDREVGR0hJSktMTU5PUFFSU1RVVldYWVo" not in text
    assert text.count("[REDACTED]") >= 3


@pytest.mark.asyncio
async def test_known_issue_agent_match_requires_workaround_status(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "known-issue.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    playbook = {
        "version": 1,
        "summary": "Use date filters.",
        "steps": ["Retry with date_from and date_to."],
        "do_not_do": [],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }
    rules = {
        "version": 1,
        "all": [
            {"field": "related_tool", "op": "eq", "value": "get_payments"},
            {"field": "normalized_error_text", "op": "contains_any", "value": ["date filter"]},
        ],
    }
    async with session_factory() as session:
        session.add(KnownIssue(
            status="acknowledged",
            category="bug",
            severity="medium",
            title="Acknowledged but not agent-facing",
            related_tool="get_payments",
            match_rules_json=json.dumps(rules),
            agent_playbook_json=json.dumps(playbook),
        ))
        await session.commit()
        match = await feedback.find_known_issue_match(
            session,
            feedback.FeedbackIncident(
                related_tool="get_payments",
                error_excerpt="date filter mismatch",
            ),
        )

    assert match is None


@pytest.mark.asyncio
async def test_auto_event_can_match_open_known_issue_without_agent_playbook(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "auto-known-issue.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 date filter failed",
    )
    fingerprint = feedback.build_error_fingerprint_hash(incident)
    async with session_factory() as session:
        session.add(KnownIssue(
            status="open",
            category="bug",
            severity="medium",
            title="Open issue still eligible for auto-event dedup",
            related_tool="get_payments",
            error_fingerprint_hash=fingerprint,
        ))
        await session.commit()

    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("HTTP 500 date filter failed"),
    )

    async with session_factory() as session:
        report_count = len((await session.execute(select(AgentFeedbackReport))).scalars().all())
        issue = (await session.execute(select(KnownIssue))).scalar_one()

    assert report_count == 1
    assert issue.report_count == 1
    assert issue.first_seen_at is not None
    assert issue.last_seen_at is not None


@pytest.mark.asyncio
async def test_auto_event_global_cap_is_consumed_only_for_matched_inserts(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "auto-cap.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "MAX_AUTO_EVENTS_PER_MINUTE", 1)
    feedback._auto_event_stamps.clear()
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("unmatched upstream failure"),
    )
    assert len(feedback._auto_event_stamps) == 0

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

    await feedback.write_auto_feedback_event(
        credentials=credentials,
        tool_name="get_payments",
        exc=ToolError("HTTP 500 date filter failed"),
    )

    async with session_factory() as session:
        report_count = len((await session.execute(select(AgentFeedbackReport))).scalars().all())

    assert report_count == 1
    assert len(feedback._auto_event_stamps) == 1


@pytest.mark.asyncio
async def test_tool_error_gets_report_hint_but_scope_denial_and_depersonalization_do_not(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "wrapper.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def failing_tool():
        raise ToolError("upstream failed")

    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_clients")
    with pytest.raises(ToolError) as exc_info:
        await wrapped()
    assert "call report_problem" in str(exc_info.value)
    assert exc_info.value.__cause__ is not None

    denied_credentials = make_runtime_credentials("clinic", "secret", scopes=())
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=denied_credentials))
    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_clients")
    with pytest.raises(ToolError) as denied:
        await wrapped()
    assert "call report_problem" not in str(denied.value)

    depersonalized_credentials = make_runtime_credentials("clinic", "secret", is_depersonalized=True)
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=depersonalized_credentials))

    async def ok_tool():
        return {"client": "raw"}

    with patch("depersonalization.sanitize_tool_result", side_effect=RuntimeError("boom")):
        wrapped = tools._wrap_tool_with_depersonalization(ok_tool, tool_name="get_clients")
        with pytest.raises(ToolError) as depersonalized:
            await wrapped()
    assert str(depersonalized.value) == "Depersonalization failed."

    normal_credentials = make_runtime_credentials("clinic", "secret")
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=normal_credentials))

    async def invalid_input_tool():
        raise ToolError("Invalid date_from format.")

    wrapped = tools._wrap_tool_with_depersonalization(invalid_input_tool, tool_name="get_clients")
    with pytest.raises(ToolError) as validation_error:
        await wrapped()
    assert str(validation_error.value) == "Invalid date_from format."
    assert "call report_problem" not in str(validation_error.value)

    async def upstream_cannot_tool():
        raise ToolError("Server cannot connect to Vetmanager upstream.")

    wrapped = tools._wrap_tool_with_depersonalization(upstream_cannot_tool, tool_name="get_clients")
    with pytest.raises(ToolError) as upstream_error:
        await wrapped()
    assert "call report_problem" in str(upstream_error.value)


@pytest.mark.asyncio
async def test_auto_event_write_is_bounded_on_augmented_error(monkeypatch, feedback_pepper):
    monkeypatch.setattr(feedback, "KNOWN_ISSUE_LOOKUP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(feedback, "AUTO_EVENT_WRITE_TIMEOUT_SECONDS", 0.01)

    async def slow_lookup(tool_name, exc):
        return None

    async def slow_auto_event(**kwargs):
        await feedback.asyncio.sleep(10)

    monkeypatch.setattr(feedback, "lookup_known_issue_for_error", slow_lookup)
    monkeypatch.setattr(feedback, "write_auto_feedback_event", slow_auto_event)
    credentials = make_runtime_credentials("clinic", "secret")

    augmented = await feedback.augment_tool_error("get_clients", credentials, ToolError("upstream failed"))

    assert "call report_problem" in str(augmented)


@pytest.mark.asyncio
async def test_wrapper_known_issue_playbook_and_auto_event_dedup(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "wrapper-known-issue.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    feedback._auto_event_stamps.clear()
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))
    incident = feedback.FeedbackIncident(
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 date filter failed",
    )
    playbook = {
        "version": 1,
        "summary": "Retry with an explicit date range.",
        "steps": ["Call get_payments with date_from and date_to."],
        "do_not_do": ["Do not retry without date filters."],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }
    async with session_factory() as session:
        session.add(KnownIssue(
            status="workaround_available",
            category="bug",
            severity="medium",
            title="Payment date filter outage",
            related_tool="get_payments",
            error_fingerprint_hash=feedback.build_error_fingerprint_hash(incident),
            agent_playbook_json=json.dumps(playbook),
        ))
        await session.commit()

    async def failing_tool():
        raise ToolError("HTTP 500 date filter failed")

    wrapped = tools._wrap_tool_with_depersonalization(failing_tool, tool_name="get_payments")
    with pytest.raises(ToolError) as first_error:
        await wrapped()

    assert "Known issue playbook" in str(first_error.value)
    assert "Retry with an explicit date range." in str(first_error.value)

    with pytest.raises(ToolError):
        await wrapped()

    async with session_factory() as session:
        reports = (await session.execute(select(AgentFeedbackReport))).scalars().all()
        issue = (await session.execute(select(KnownIssue))).scalar_one()

    assert len(reports) == 1
    assert reports[0].source == "auto"
    assert issue.report_count == 1


@pytest.mark.asyncio
async def test_report_problem_rate_limits_token_account_and_window(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
    feedback_pepper,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "rate-limits.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "REPORT_TOKEN_LIMIT_PER_HOUR", 2)
    monkeypatch.setattr(feedback, "REPORT_ACCOUNT_LIMIT_PER_HOUR", 3)
    old_created_at = feedback._now() - timedelta(hours=2)
    async with session_factory() as session:
        session.add_all([
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="low",
                status="new",
                account_id=10,
                bearer_token_id=20,
                summary="token report 1",
                details="details",
            ),
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="low",
                status="new",
                account_id=10,
                bearer_token_id=20,
                summary="token report 2",
                details="details",
            ),
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="low",
                status="new",
                account_id=30,
                bearer_token_id=40,
                summary="old token report",
                details="details",
                created_at=old_created_at,
            ),
        ])
        await session.commit()

    token_credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)
    with pytest.raises(ToolError, match="this token"):
        await feedback.create_feedback_report(
            credentials=token_credentials,
            category="bug",
            severity="low",
            summary="new token report",
            details="details",
        )

    old_window_credentials = make_runtime_credentials("clinic", "secret", account_id=30, bearer_token_id=40)
    result = await feedback.create_feedback_report(
        credentials=old_window_credentials,
        category="bug",
        severity="low",
        summary="outside window is ignored",
        details="details",
    )
    assert result["ok"] is True

    account_credentials = make_runtime_credentials("clinic", "secret", account_id=50, bearer_token_id=None)
    async with session_factory() as session:
        session.add_all([
            AgentFeedbackReport(
                source="model",
                category="bug",
                severity="low",
                status="new",
                account_id=50,
                bearer_token_id=None,
                summary=f"account report {index}",
                details="details",
            )
            for index in range(3)
        ])
        await session.commit()

    with pytest.raises(ToolError, match="this account"):
        await feedback.create_feedback_report(
            credentials=account_credentials,
            category="bug",
            severity="low",
            summary="new account report",
            details="details",
        )


def test_feedback_runtime_config_requires_pepper_for_postgres(monkeypatch):
    monkeypatch.delenv("FEEDBACK_FINGERPRINT_PEPPER", raising=False)

    with pytest.raises(RuntimeError, match="FEEDBACK_FINGERPRINT_PEPPER"):
        feedback.validate_feedback_runtime_config(database_url="postgresql+asyncpg://user:pass@db/app")
    with pytest.raises(RuntimeError, match="FEEDBACK_FINGERPRINT_PEPPER"):
        feedback._fingerprint_pepper()

    feedback.validate_feedback_runtime_config(database_url="sqlite+aiosqlite:///./data/test.db")

    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "prod-pepper")
    feedback.validate_feedback_runtime_config(database_url="postgresql+asyncpg://user:pass@db/app")


@pytest.mark.asyncio
async def test_structured_report_without_pepper_persists_without_fingerprint_on_sqlite(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
):
    monkeypatch.delenv("FEEDBACK_FINGERPRINT_PEPPER", raising=False)
    session_factory = await sqlite_session_factory_builder(tmp_path / "no-pepper.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    credentials = make_runtime_credentials("clinic", "secret", account_id=10, bearer_token_id=20)

    result = await feedback.create_feedback_report(
        credentials=credentials,
        category="bug",
        severity="low",
        summary="structured report",
        details="details",
        related_tool="get_payments",
        error_code="ToolError",
        error_excerpt="HTTP 500 upstream failed",
    )

    async with session_factory() as session:
        report = await session.get(AgentFeedbackReport, result["feedback_id"])

    assert report is not None
    assert report.error_fingerprint_hash is None


def test_report_problem_baseline_scope_requires_authenticated_non_empty_scopes():
    credentials = make_runtime_credentials("clinic", "secret", scopes=("clients.read",))
    tools._ensure_tool_scopes_allowed("report_problem", credentials)

    empty_credentials = make_runtime_credentials("clinic", "secret", scopes=())
    with pytest.raises(ToolError):
        tools._ensure_tool_scopes_allowed("report_problem", empty_credentials)


@pytest.mark.asyncio
async def test_triage_retention_cleanup_keeps_active_reports(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "triage.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        old_done = AgentFeedbackReport(
            source="model",
            category="bug",
            severity="low",
            status="linked",
            summary="old linked",
            details="done",
        )
        active = AgentFeedbackReport(
            source="model",
            category="bug",
            severity="low",
            status="new",
            summary="old active",
            details="still triage",
        )
        session.add_all([old_done, active])
        await session.commit()

    await triage_cli._retention(type("Args", (), {"days": 0})())

    async with session_factory() as session:
        rows = (await session.execute(select(AgentFeedbackReport))).scalars().all()

    assert [row.summary for row in rows] == ["old active"]


@pytest.mark.asyncio
async def test_triage_promote_validates_rules_and_sanitizes_agent_fields(
    sqlite_session_factory_builder,
    tmp_path,
    monkeypatch,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "triage-promote.db")
    monkeypatch.setattr(triage_cli, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        report = AgentFeedbackReport(
            source="model",
            category="bug",
            severity="medium",
            status="new",
            summary="Payment failure",
            details="details",
            related_tool="get_payments",
        )
        session.add(report)
        await session.commit()
        report_id = report.id

    invalid_rules_path = tmp_path / "invalid-rules.json"
    invalid_rules_path.write_text(json.dumps({"version": 1, "all": [{"field": "bad", "op": "eq", "value": "x"}]}))
    with pytest.raises(SystemExit, match="Invalid match rules JSON"):
        await triage_cli._promote(SimpleNamespace(
            report_id=report_id,
            title="",
            status="workaround_available",
            public_summary=None,
            workaround=None,
            playbook_json=None,
            match_rules_json=str(invalid_rules_path),
        ))

    playbook_path = tmp_path / "playbook.json"
    playbook_path.write_text(json.dumps({
        "version": 1,
        "summary": "Retry without token=secret-1234567890",
        "steps": ["Use date_from/date_to."],
        "do_not_do": [],
        "recommended_tool_sequence": ["get_payments"],
        "safe_to_retry": True,
    }))
    valid_rules_path = tmp_path / "valid-rules.json"
    valid_rules_path.write_text(json.dumps({
        "version": 1,
        "all": [{"field": "related_tool", "op": "eq", "value": "get_payments"}],
    }))

    await triage_cli._promote(SimpleNamespace(
        report_id=report_id,
        title="Payment workaround for test@example.com",
        status="workaround_available",
        public_summary="Contact test@example.com saw a failure.",
        workaround="Authorization: Bearer abcdef1234567890 should not persist.",
        playbook_json=str(playbook_path),
        match_rules_json=str(valid_rules_path),
    ))

    async with session_factory() as session:
        issue = (await session.execute(select(KnownIssue))).scalar_one()

    assert "test@example.com" not in issue.title
    assert "test@example.com" not in (issue.public_summary or "")
    assert "abcdef1234567890" not in (issue.workaround or "")
    assert "secret-1234567890" not in (issue.agent_playbook_json or "")
    assert feedback.validate_match_rules_json(issue.match_rules_json) is not None
    assert feedback.validate_agent_playbook(issue.agent_playbook_json) is not None
