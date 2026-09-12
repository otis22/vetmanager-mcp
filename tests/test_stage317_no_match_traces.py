"""Stage 317: unmatched failures remain actionable without retaining raw errors."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError
from sqlalchemy import select

import agent_feedback_service as feedback
import scripts.triage_agent_feedback as triage
from exceptions import VetmanagerError
from storage_models import KnownIssueNoMatchTrace


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage317-test-pepper")


@pytest.mark.asyncio
async def test_no_match_failure_writes_sanitized_trace_and_triage_aggregates_it(
    sqlite_session_factory_builder, tmp_path, monkeypatch, capsys, feedback_pepper,
):
    factory = await sqlite_session_factory_builder(tmp_path / "stage317.db")
    monkeypatch.setattr(feedback, "get_session_factory", lambda: factory)
    monkeypatch.setattr(triage, "get_session_factory", lambda: factory)
    credentials = SimpleNamespace(account_id=None, bearer_token_id=None)
    error = VetmanagerError("StartReport failed at tenant.vetmanager.ru/rest/42 due to export guard", 403)

    await feedback.augment_tool_error("start_report_export", credentials, ToolError(str(error)), incident_source=error)

    async with factory() as session:
        trace = (await session.execute(select(KnownIssueNoMatchTrace))).scalar_one()
    assert trace.related_tool == "start_report_export"
    assert trace.http_status == 403
    assert "tenant.vetmanager.ru" not in trace.normalized_error_text
    assert "42" not in trace.normalized_error_text

    await triage._no_match_traces(SimpleNamespace(days=30, limit=20))
    output = capsys.readouterr().out
    assert "start_report_export" in output
    assert "tenant.vetmanager.ru" not in output
