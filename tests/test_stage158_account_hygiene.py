"""Stage 158 — soft-archive zombie accounts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update

from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_DISABLED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
    TOKEN_EVENT_CREATED,
)
from scripts.product_metrics_report import collect_metrics
from storage_models import (
    Account,
    AgentFeedbackReport,
    FEEDBACK_CATEGORY_BUG,
    FEEDBACK_SEVERITY_LOW,
    FEEDBACK_SOURCE_MODEL,
    FEEDBACK_STATUS_NEW,
    KnownIssue,
    KnownIssueMatchEvent,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TokenUsageLog,
    TokenUsageStat,
    VetmanagerConnection,
)


NOW = datetime(2026, 5, 3, 12, 0, tzinfo=timezone.utc)


async def _account(session, email: str, *, age_days: int) -> Account:
    account = Account(
        email=email,
        password_hash="h",
        status="active",
        created_at=NOW - timedelta(days=age_days),
        updated_at=NOW - timedelta(days=age_days),
    )
    session.add(account)
    await session.flush()
    return account


async def _token(session, account: Account, suffix: str) -> ServiceBearerToken:
    token = ServiceBearerToken(
        account_id=account.id,
        name=f"token-{suffix}",
        token_prefix=f"sbt_{suffix}",
        token_hash=f"hash_{suffix}",
        status=TOKEN_STATUS_ACTIVE,
        created_at=NOW - timedelta(days=40),
    )
    session.add(token)
    await session.flush()
    return token


@pytest.mark.asyncio
async def test_archive_criteria_and_restore_contract(sqlite_session_factory_builder, tmp_path, monkeypatch):
    import scripts.archive_zombie_accounts as archive

    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158.db")
    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)

    async with session_factory() as session:
        zombie = await _account(session, "zombie@example.com", age_days=60)
        zombie_token = await _token(session, zombie, "zombie")
        session.add(TokenUsageLog(
            bearer_token_id=zombie_token.id,
            event_type=TOKEN_EVENT_CREATED,
            event_at=NOW - timedelta(days=50),
        ))
        zombie_two = await _account(session, "zombie-two@example.com", age_days=60)

        connected = await _account(session, "connected@example.com", age_days=60)
        session.add(VetmanagerConnection(
            account_id=connected.id,
            auth_mode="domain_api_key",
            status="active",
        ))

        failed = await _account(session, "failed@example.com", age_days=60)
        failed_token = await _token(session, failed, "failed")
        session.add(TokenUsageLog(
            bearer_token_id=failed_token.id,
            event_type=TOKEN_EVENT_AUTH_FAILED_DISABLED,
            event_at=NOW - timedelta(days=2),
        ))

        feedback = await _account(session, "feedback@example.com", age_days=60)
        session.add(AgentFeedbackReport(
            source=FEEDBACK_SOURCE_MODEL,
            category=FEEDBACK_CATEGORY_BUG,
            severity=FEEDBACK_SEVERITY_LOW,
            status=FEEDBACK_STATUS_NEW,
            account_id=feedback.id,
            summary="summary",
            details="details",
        ))

        matched = await _account(session, "matched@example.com", age_days=60)
        issue = KnownIssue(status="open", category="bug", severity="low", title="known")
        session.add(issue)
        await session.flush()
        session.add(KnownIssueMatchEvent(
            known_issue_id=issue.id,
            account_id=matched.id,
            source="auto",
        ))

        young = await _account(session, "young@example.com", age_days=5)
        await _token(session, young, "young")
        await session.commit()
        zombie_id = zombie.id
        zombie_two_id = zombie_two.id

    dry = await archive.archive_zombie_accounts(apply=False, now=NOW)
    assert dry["matched"] == 2
    assert dry["archived"] == 0
    assert dry["candidate_ids"] == [zombie_id, zombie_two_id]
    assert dry["archived_ids"] == []

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(Account).where(Account.archived_at.isnot(None))) == 0

    applied = await archive.archive_zombie_accounts(apply=True, now=NOW)
    assert applied["matched"] == 2
    assert applied["archived"] == 2
    assert applied["candidate_ids"] == [zombie_id, zombie_two_id]
    assert applied["archived_ids"] == [zombie_id, zombie_two_id]

    second = await archive.archive_zombie_accounts(apply=True, now=NOW)
    assert second["matched"] == 0
    assert second["archived"] == 0

    dry_restore = await archive.restore_account(zombie_id, apply=False)
    assert dry_restore == {
        "status": "ok",
        "restored": 0,
        "would_restore": 1,
        "already_active": 0,
        "not_found": 0,
        "account_id": zombie_id,
    }
    async with session_factory() as session:
        assert (await session.get(Account, zombie_id)).archived_at is not None

    restored = await archive.restore_account(zombie_id, apply=True)
    assert restored == {"status": "ok", "restored": 1, "already_active": 0, "not_found": 0, "account_id": zombie_id}
    already = await archive.restore_account(zombie_id, apply=True)
    assert already == {"status": "ok", "restored": 0, "already_active": 1, "not_found": 0, "account_id": zombie_id}
    missing = await archive.restore_account(999999, apply=True)
    assert missing == {"status": "not_found", "restored": 0, "already_active": 0, "not_found": 1, "account_id": 999999}


@pytest.mark.asyncio
async def test_archive_apply_rechecks_predicate_after_stale_candidate_select(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    import scripts.archive_zombie_accounts as archive

    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158-stale.db")
    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        account = await _account(session, "stale@example.com", age_days=60)
        token = await _token(session, account, "stale")
        await session.commit()
        account_id = account.id
        token_id = token.id

    original_candidate_ids = archive._candidate_ids

    async def stale_candidate_ids(session, *, now):
        ids = await original_candidate_ids(session, now=now)
        if ids:
            session.add(TokenUsageLog(
                bearer_token_id=token_id,
                event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
                event_at=now,
            ))
            await session.flush()
        return ids

    monkeypatch.setattr(archive, "_candidate_ids", stale_candidate_ids)

    applied = await archive.archive_zombie_accounts(apply=True, now=NOW)

    assert applied["matched"] == 1
    assert applied["archived"] == 0
    assert applied["skipped"] == 1
    assert applied["candidate_ids"] == [account_id]
    assert applied["archived_ids"] == []
    async with session_factory() as session:
        assert (await session.get(Account, account_id)).archived_at is None


@pytest.mark.asyncio
async def test_archive_ids_only_report_rows_updated_by_guarded_write(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    import scripts.archive_zombie_accounts as archive

    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158-returning.db")
    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        account = await _account(session, "already-archived-race@example.com", age_days=60)
        await _token(session, account, "race")
        await session.commit()
        account_id = account.id

    original_candidate_ids = archive._candidate_ids

    async def externally_archived_candidate_ids(session, *, now):
        ids = await original_candidate_ids(session, now=now)
        if ids:
            await session.execute(
                update(Account)
                .where(Account.id == account_id)
                .values(archived_at=now - timedelta(seconds=1))
            )
            await session.flush()
        return ids

    monkeypatch.setattr(archive, "_candidate_ids", externally_archived_candidate_ids)

    applied = await archive.archive_zombie_accounts(apply=True, now=NOW)

    assert applied["matched"] == 1
    assert applied["archived"] == 0
    assert applied["skipped"] == 1
    assert applied["candidate_ids"] == [account_id]
    assert applied["archived_ids"] == []


@pytest.mark.asyncio
async def test_archive_apply_only_archives_initial_candidates_when_new_candidate_appears(
    sqlite_session_factory_builder, tmp_path, monkeypatch,
):
    import scripts.archive_zombie_accounts as archive

    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158-new-candidate.db")
    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        existing = await _account(session, "existing-candidate@example.com", age_days=60)
        fresh = await _account(session, "fresh-candidate@example.com", age_days=5)
        await session.commit()
        existing_id = existing.id
        fresh_id = fresh.id

    original_candidate_ids = archive._candidate_ids

    async def candidate_ids_then_new_candidate(session, *, now):
        ids = await original_candidate_ids(session, now=now)
        if ids:
            await session.execute(
                update(Account)
                .where(Account.id == fresh_id)
                .values(created_at=now - timedelta(days=60))
            )
            await session.flush()
        return ids

    monkeypatch.setattr(archive, "_candidate_ids", candidate_ids_then_new_candidate)

    applied = await archive.archive_zombie_accounts(apply=True, now=NOW)

    assert applied["matched"] == 1
    assert applied["archived"] == 1
    assert applied["skipped"] == 0
    assert applied["candidate_ids"] == [existing_id]
    assert applied["archived_ids"] == [existing_id]
    async with session_factory() as session:
        assert (await session.get(Account, fresh_id)).archived_at is None


@pytest.mark.asyncio
async def test_archive_cli_outputs_no_email(sqlite_session_factory_builder, tmp_path, monkeypatch, capsys):
    import scripts.archive_zombie_accounts as archive

    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158-cli.db")
    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)
    async with session_factory() as session:
        account = await _account(session, "private@example.com", age_days=60)
        await _token(session, account, "private")
        await session.commit()
        account_id = account.id

    monkeypatch.setattr(archive, "_now", lambda: NOW)
    parser = archive._build_parser()
    assert await archive._main_async(parser.parse_args(["--dry-run"])) == 0
    assert "private@example.com" not in capsys.readouterr().out

    assert await archive._main_async(
        parser.parse_args(["restore", "--account-id", str(account_id), "--dry-run"])
    ) == 0
    assert "private@example.com" not in capsys.readouterr().out

    assert await archive._main_async(
        parser.parse_args(["--dry-run", "restore", "--account-id", str(account_id)])
    ) == 0
    assert "private@example.com" not in capsys.readouterr().out

    assert await archive._main_async(
        parser.parse_args(["restore", "--account-id", "999999", "--dry-run"])
    ) == 1
    assert "private@example.com" not in capsys.readouterr().out


@pytest.mark.asyncio
async def test_product_metrics_excludes_archived_accounts_but_keeps_token_signal(
    sqlite_session_factory_builder, tmp_path,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "stage158-metrics.db")
    async with session_factory() as session:
        live = await _account(session, "live@example.com", age_days=60)
        live_token = await _token(session, live, "live")
        session.add(TokenUsageStat(
            bearer_token_id=live_token.id,
            request_count=10,
            last_used_at=NOW - timedelta(days=1),
        ))
        archived = await _account(session, "archived@example.com", age_days=60)
        archived.archived_at = NOW
        archived_token = await _token(session, archived, "archived")
        session.add(TokenUsageStat(
            bearer_token_id=archived_token.id,
            request_count=999,
            last_used_at=NOW - timedelta(days=1),
        ))
        await session.commit()

    metrics = await collect_metrics(session_factory, now=NOW, top_n=10)

    assert metrics["accounts"]["archived"] == 1
    assert metrics["accounts"]["total"] == 1
    assert metrics["accounts"]["live_7d"] == 1
    assert metrics["tokens"]["total_active"] == 2
    assert [row["account_id"] for row in metrics["requests"]["top_accounts"]] == [live.id]
