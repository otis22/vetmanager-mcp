"""Stage 159: feedback block in product metrics report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from scripts.product_metrics_report import collect_metrics, format_json, format_markdown
from storage_models import (
    AgentFeedbackReport,
    FEEDBACK_CATEGORY_BAD_DESCRIPTION,
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_CATEGORY_CONTRACT,
    FEEDBACK_CATEGORY_DOCS,
    FEEDBACK_CATEGORY_MISSING_TOOL,
    FEEDBACK_CATEGORY_OTHER,
    FEEDBACK_CATEGORY_PERF,
    FEEDBACK_SOURCE_AUTO,
    FEEDBACK_SOURCE_MODEL,
    FEEDBACK_SOURCE_USER_COMPLAINT,
    FEEDBACK_STATUS_GROUPED,
    FEEDBACK_STATUS_IGNORED,
    FEEDBACK_STATUS_LINKED,
    FEEDBACK_STATUS_NEW,
    FEEDBACK_STATUS_TRIAGED,
    FEEDBACK_SEVERITY_HIGH,
    FEEDBACK_SEVERITY_LOW,
    FEEDBACK_SEVERITY_MEDIUM,
    KnownIssue,
    KnownIssueMatchEvent,
)


@pytest.fixture
def now_utc() -> datetime:
    return datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def feedback_session(tmp_path: Path, sqlite_session_factory_builder, now_utc):
    factory = await sqlite_session_factory_builder(tmp_path / "stage159-feedback.db")
    async with factory() as session:
        reports = [
            AgentFeedbackReport(
                source=FEEDBACK_SOURCE_MODEL,
                category=FEEDBACK_CATEGORY_BUG,
                severity=FEEDBACK_SEVERITY_HIGH,
                status=FEEDBACK_STATUS_NEW,
                related_tool="get_clients",
                summary="client <client> lookup fails",
                details="safe report details",
                created_at=now_utc - timedelta(hours=2),
                possible_pii=True,
            ),
            AgentFeedbackReport(
                source=FEEDBACK_SOURCE_MODEL,
                category=FEEDBACK_CATEGORY_BUG,
                severity=FEEDBACK_SEVERITY_MEDIUM,
                status=FEEDBACK_STATUS_TRIAGED,
                related_tool="get_clients",
                summary="another report",
                details="safe report details",
                created_at=now_utc - timedelta(days=3),
                possible_pii=False,
            ),
            AgentFeedbackReport(
                source=FEEDBACK_SOURCE_AUTO,
                category=FEEDBACK_CATEGORY_CONTRACT,
                severity=FEEDBACK_SEVERITY_LOW,
                status=FEEDBACK_STATUS_LINKED,
                related_tool="create_admission",
                summary="auto report",
                details="safe report details",
                created_at=now_utc - timedelta(days=10),
                possible_pii=False,
            ),
            AgentFeedbackReport(
                source=FEEDBACK_SOURCE_USER_COMPLAINT,
                category=FEEDBACK_CATEGORY_DOCS,
                severity=FEEDBACK_SEVERITY_LOW,
                status=FEEDBACK_STATUS_GROUPED,
                related_tool=None,
                summary="user complaint",
                details="safe report details",
                created_at=now_utc - timedelta(days=20),
                possible_pii=False,
            ),
            AgentFeedbackReport(
                source=FEEDBACK_SOURCE_MODEL,
                category=FEEDBACK_CATEGORY_PERF,
                severity=FEEDBACK_SEVERITY_LOW,
                status=FEEDBACK_STATUS_IGNORED,
                related_tool="old_tool",
                summary="old report must be out of 30d",
                details="safe report details",
                created_at=now_utc - timedelta(days=40),
                possible_pii=True,
            ),
        ]
        session.add_all(reports)
        issue_with_pii_title = KnownIssue(
            status="open",
            category=FEEDBACK_CATEGORY_BUG,
            severity=FEEDBACK_SEVERITY_MEDIUM,
            title="Problem for owner alice@example.com",
            related_tool="get_clients",
        )
        issue_two = KnownIssue(
            status="acknowledged",
            category=FEEDBACK_CATEGORY_BAD_DESCRIPTION,
            severity=FEEDBACK_SEVERITY_LOW,
            title="Description mismatch",
            related_tool="get_pets",
        )
        session.add_all([issue_with_pii_title, issue_two])
        await session.flush()
        for _ in range(3):
            session.add(KnownIssueMatchEvent(
                known_issue_id=issue_with_pii_title.id,
                related_tool="get_clients",
                source="injection",
                account_id=10,
                bearer_token_id=20,
                created_at=now_utc - timedelta(days=2),
            ))
        session.add(KnownIssueMatchEvent(
            known_issue_id=issue_with_pii_title.id,
            related_tool="get_clients",
            source="report",
            account_id=11,
            bearer_token_id=21,
            created_at=now_utc - timedelta(days=8),
        ))
        session.add(KnownIssueMatchEvent(
            known_issue_id=issue_two.id,
            related_tool="get_pets",
            source="auto",
            account_id=None,
            bearer_token_id=22,
            created_at=now_utc - timedelta(days=3),
        ))
        session.add(KnownIssueMatchEvent(
            known_issue_id=issue_two.id,
            related_tool="get_pets",
            source="auto",
            account_id=99,
            bearer_token_id=99,
            created_at=now_utc - timedelta(days=40),
        ))
        await session.commit()
    return factory


@pytest.mark.asyncio
async def test_feedback_metrics_collected_with_windows_and_breakdowns(feedback_session, now_utc):
    metrics = await collect_metrics(feedback_session, now=now_utc, top_n=2)
    feedback = metrics["feedback"]
    reports = feedback["reports"]
    events = feedback["match_events"]

    assert reports["total_24h"] == 1
    assert reports["total_7d"] == 2
    assert reports["total_30d"] == 4
    assert reports["new_open_30d"] == 1
    assert reports["possible_pii_30d"] == 1
    assert reports["by_source_30d"] == {
        FEEDBACK_SOURCE_MODEL: 2,
        FEEDBACK_SOURCE_AUTO: 1,
        FEEDBACK_SOURCE_USER_COMPLAINT: 1,
    }
    assert reports["by_status_30d"] == {
        FEEDBACK_STATUS_NEW: 1,
        FEEDBACK_STATUS_GROUPED: 1,
        FEEDBACK_STATUS_TRIAGED: 1,
        FEEDBACK_STATUS_LINKED: 1,
        FEEDBACK_STATUS_IGNORED: 0,
    }
    assert reports["by_severity_30d"] == {
        FEEDBACK_SEVERITY_LOW: 2,
        FEEDBACK_SEVERITY_MEDIUM: 1,
        FEEDBACK_SEVERITY_HIGH: 1,
    }
    assert reports["by_category_30d"] == {
        FEEDBACK_CATEGORY_BUG: 2,
        FEEDBACK_CATEGORY_MISSING_TOOL: 0,
        FEEDBACK_CATEGORY_BAD_DESCRIPTION: 0,
        FEEDBACK_CATEGORY_CONTRACT: 1,
        FEEDBACK_CATEGORY_PERF: 0,
        FEEDBACK_CATEGORY_DOCS: 1,
        FEEDBACK_CATEGORY_OTHER: 0,
    }
    assert reports["top_tools_30d"] == [
        {"tool": "get_clients", "reports": 2},
        {"tool": "create_admission", "reports": 1},
    ]

    assert events["total_7d"] == 4
    assert events["total_30d"] == 5
    assert events["by_source_7d"] == {"injection": 3, "report": 0, "auto": 1}
    assert events["by_source_30d"] == {"injection": 3, "report": 1, "auto": 1}
    assert events["top_known_issues_30d"][0]["events"] == 4
    assert events["top_known_issues_30d"][0]["distinct_accounts"] == 2
    assert events["top_known_issues_30d"][0]["distinct_tokens"] == 2
    assert isinstance(events["top_known_issues_30d"][0]["distinct_accounts"], int)
    assert "alice@example.com" not in events["top_known_issues_30d"][0]["title"]


@pytest.mark.asyncio
async def test_feedback_metrics_format_markdown_and_json_without_raw_feedback(
    feedback_session,
    now_utc,
):
    metrics = await collect_metrics(feedback_session, now=now_utc, top_n=5)
    markdown = format_markdown(metrics, now=now_utc)
    json_text = format_json(metrics, now=now_utc)
    parsed = json.loads(json_text)

    assert "## Feedback" in markdown
    assert parsed["feedback"]["reports"]["total_30d"] == 4
    assert parsed["feedback"]["match_events"]["total_30d"] == 5

    forbidden = [
        "client <client> lookup fails",
        "safe report details",
        "old report must be out of 30d",
        "alice@example.com",
        "account_id",
        "bearer_token_id",
        "summary",
        "details",
        "error_excerpt",
        "params_shape_json",
        "suggested_fix",
        "reproduce",
        "Bearer ",
        "X-REST-API-KEY",
    ]
    for output in (markdown, json_text):
        for needle in forbidden:
            assert needle not in output
