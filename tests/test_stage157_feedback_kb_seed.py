"""Stage 157 — known issue seed bootstrap and feedback write-path diagnostic."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

import pytest
from sqlalchemy import func, select

import agent_feedback_service as feedback
from storage_models import Account, AgentFeedbackReport, KnownIssue, KnownIssueMatchEvent, ServiceBearerToken


@pytest.fixture
def feedback_pepper(monkeypatch):
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage157-test-pepper")


@pytest.mark.asyncio
async def test_seed_definitions_validate() -> None:
    import scripts.seed_known_issues as seed

    seed.validate_seed_definitions()
    assert 5 <= len(seed.SEED_ISSUES) <= 10
    assert all(item.title.startswith(f"[seed:{item.slug}] ") for item in seed.SEED_ISSUES)


@pytest.mark.asyncio
async def test_seed_apply_is_idempotent_and_preserves_counters(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "seed.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)

    first = await seed.seed_known_issues(apply=True)
    second = await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        rows = (await session.execute(select(KnownIssue))).scalars().all()
        target = rows[0]
        target.report_count = 7
        target.first_seen_at = datetime(2026, 5, 1, tzinfo=timezone.utc)
        target.last_seen_at = datetime(2026, 5, 2, tzinfo=timezone.utc)
        await session.commit()

    third = await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        count = await session.scalar(select(func.count()).select_from(KnownIssue))
        target = (
            await session.execute(
                select(KnownIssue).where(KnownIssue.title == seed.SEED_ISSUES[0].title)
            )
        ).scalar_one()

    assert first["created"] == len(seed.SEED_ISSUES)
    assert second["unchanged"] == len(seed.SEED_ISSUES)
    assert third["unchanged"] == len(seed.SEED_ISSUES)
    assert count == len(seed.SEED_ISSUES)
    assert target.report_count == 7
    assert target.first_seen_at is not None and target.first_seen_at.date().isoformat() == "2026-05-01"
    assert target.last_seen_at is not None and target.last_seen_at.date().isoformat() == "2026-05-02"


@pytest.mark.asyncio
async def test_seed_apply_rejects_duplicate_seed_marker(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "dupes.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    marker = seed.seed_marker(seed.SEED_ISSUES[0].slug)
    async with session_factory() as session:
        session.add_all([
            KnownIssue(status="open", category="bug", severity="low", title=f"{marker} one"),
            KnownIssue(status="open", category="bug", severity="low", title=f"{marker} two"),
        ])
        await session.commit()

    with pytest.raises(seed.SeedKnownIssuesError, match="duplicate_seed_rows"):
        await seed.seed_known_issues(apply=True)


@pytest.mark.asyncio
async def test_seeded_issue_matches_agent_playbook(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "match.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(
            session,
            feedback.FeedbackIncident(
                related_tool="create_admission",
                error_code="ToolError",
                error_excerpt="The admission date field was ignored; use admission_date.",
            ),
        )

    assert match is not None
    assert match.title.startswith("[seed:admission-create-date-field] ")
    assert match.playbook["safe_to_retry"] is True


@pytest.mark.asyncio
async def test_seeded_report_ai_goods_good_id_issue_matches_data_error(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "report-ai-good-id.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(
            session,
            feedback.FeedbackIncident(
                related_tool="get_report_ai_job_data",
                error_code="ToolError",
                error_excerpt="HTTP 500 PREVIEW_FAILED — Unknown column 'good.id' in field list",
            ),
        )

    assert match is not None
    assert match.title.startswith("[seed:report-ai-goods-good-id-preview] ")
    assert match.playbook["safe_to_retry"] is True
    assert match.playbook["recommended_tool_sequence"] == [
        "create_report_ai_job",
        "get_report_ai_job",
    ]


@pytest.mark.asyncio
async def test_seeded_report_ai_goods_good_id_issue_ignores_generic_preview_failed(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "report-ai-generic-preview.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(
            session,
            feedback.FeedbackIncident(
                related_tool="get_report_ai_job_data",
                error_code="ToolError",
                error_excerpt="HTTP 500 PREVIEW_FAILED — Renderer timeout",
            ),
        )

    assert match is None


@pytest.mark.asyncio
async def test_seeded_report_ai_goods_good_id_issue_ignores_generic_goods_preview(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "report-ai-generic-goods.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    await seed.seed_known_issues(apply=True)

    async with session_factory() as session:
        match = await feedback.find_known_issue_match(
            session,
            feedback.FeedbackIncident(
                related_tool="get_report_ai_job_data",
                error_code="ToolError",
                error_excerpt="HTTP 500 PREVIEW_FAILED — ошибка товарного отчёта по остаткам",
            ),
        )

    assert match is None


@pytest.mark.asyncio
async def test_diagnostic_requires_pepper_before_apply(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "diag-no-pepper.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    monkeypatch.delenv("FEEDBACK_FINGERPRINT_PEPPER", raising=False)

    result = await seed.diagnostic_auto_event(
        apply=True,
        account_id=1,
        bearer_token_id=2,
        run_id="rid-abcd-efab",
    )

    assert result["status"] == "failed"
    assert result["skipped_reason"] == "missing_feedback_fingerprint_pepper"


@pytest.mark.asyncio
async def test_diagnostic_exercises_wrapper_and_creates_run_specific_auto_rows(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "diag.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        account = Account(email="stage157@example.com", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(
            account_id=account.id,
            name="stage157",
            token_prefix="sbt_stage157",
            token_hash="stage157_hash_" + "x" * 48,
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
        event_count = await session.scalar(
            select(func.count())
            .select_from(KnownIssueMatchEvent)
            .where(KnownIssueMatchEvent.error_fingerprint_hash == result["error_fingerprint_hash"])
            .where(KnownIssueMatchEvent.account_id == account.id)
            .where(KnownIssueMatchEvent.bearer_token_id == token.id)
        )
        report_count = await session.scalar(
            select(func.count())
            .select_from(AgentFeedbackReport)
            .where(AgentFeedbackReport.error_fingerprint_hash == result["error_fingerprint_hash"])
            .where(AgentFeedbackReport.account_id == account.id)
            .where(AgentFeedbackReport.bearer_token_id == token.id)
        )

    assert result["status"] == "ok"
    assert result["event_created"] is True
    assert result["report_created"] is True
    assert event_count == 1
    assert report_count == 1
    assert result["account_id_present"] is True
    assert result["bearer_token_id_present"] is True


@pytest.mark.asyncio
async def test_diagnostic_rejects_missing_or_inactive_identity(
    sqlite_session_factory_builder,
    tmp_path: Path,
    monkeypatch,
    feedback_pepper,
) -> None:
    import scripts.seed_known_issues as seed

    session_factory = await sqlite_session_factory_builder(tmp_path / "diag-identity.db")
    monkeypatch.setattr(seed, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(feedback, "get_session_factory", lambda: session_factory)

    result = await seed.diagnostic_auto_event(
        apply=True,
        account_id=12345,
        bearer_token_id=None,
        run_id="rid-abcd-efab",
    )

    async with session_factory() as session:
        diagnostic_count = await session.scalar(
            select(func.count())
            .select_from(KnownIssue)
            .where(KnownIssue.related_tool == seed.DIAGNOSTIC_TOOL)
        )

    assert result["status"] == "failed"
    assert result["skipped_reason"] == "identity_not_found"
    assert result["missing"] == "account_id"
    assert diagnostic_count == 0


def test_diagnostic_cli_requires_explicit_mode(monkeypatch, capsys) -> None:
    import scripts.seed_known_issues as seed

    monkeypatch.setattr(sys, "argv", ["seed_known_issues.py", "diagnostic-auto-event"])

    with pytest.raises(SystemExit) as exc:
        seed.main()

    assert exc.value.code == 2
    assert "choose exactly one of --dry-run or --apply" in capsys.readouterr().err


def test_generated_run_ids_survive_normalization_uniquely() -> None:
    import scripts.seed_known_issues as seed

    run_id_a = seed.generate_run_id()
    run_id_b = seed.generate_run_id()

    assert run_id_a != run_id_b
    assert feedback.normalize_error_text(run_id_a) != feedback.normalize_error_text(run_id_b)


def test_shared_tool_wrapper_still_calls_augment_tool_error() -> None:
    source = Path("tools/__init__.py").read_text(encoding="utf-8")

    assert "augment_tool_error" in source
    assert "raise await augment_tool_error" in source
