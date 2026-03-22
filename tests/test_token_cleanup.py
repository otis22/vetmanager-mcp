"""Unit tests for expired bearer-token cleanup policy."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from storage_models import Account, ServiceBearerToken, TokenUsageLog
from token_cleanup import sync_expired_tokens


@pytest.mark.asyncio
async def test_sync_expired_tokens_marks_active_token_expired_and_logs_event(
    tmp_path: Path,
    sqlite_session_factory_builder,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "token-cleanup.db")
    now = datetime(2026, 3, 22, 10, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = Account(email="cleanup@example.com", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(
            account_id=account.id,
            name="Expired token",
            token_prefix="vm_st_demo",
            token_hash="hash",
            status="active",
            expires_at=now - timedelta(minutes=1),
        )
        session.add(token)
        await session.commit()

    async with session_factory() as session:
        updated = await sync_expired_tokens(session, account_id=1, now=now)

    async with session_factory() as session:
        token = await session.get(ServiceBearerToken, 1)
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert updated == 1
    assert token is not None
    assert token.status == "expired"
    assert [log.event_type for log in logs] == ["token_expired"]


@pytest.mark.asyncio
async def test_sync_expired_tokens_does_not_duplicate_event_for_already_expired_token(
    tmp_path: Path,
    sqlite_session_factory_builder,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "token-cleanup.db")
    now = datetime(2026, 3, 22, 11, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = Account(email="cleanup@example.com", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(
            account_id=account.id,
            name="Expired token",
            token_prefix="vm_st_demo",
            token_hash="hash",
            status="active",
            expires_at=now - timedelta(minutes=1),
        )
        session.add(token)
        await session.commit()

    async with session_factory() as session:
        first = await sync_expired_tokens(session, account_id=1, now=now)
    async with session_factory() as session:
        second = await sync_expired_tokens(session, account_id=1, now=now)

    async with session_factory() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert first == 1
    assert second == 0
    assert [log.event_type for log in logs] == ["token_expired"]


@pytest.mark.asyncio
async def test_sync_expired_tokens_does_not_override_revoked_token(
    tmp_path: Path,
    sqlite_session_factory_builder,
):
    session_factory = await sqlite_session_factory_builder(tmp_path / "token-cleanup.db")
    now = datetime(2026, 3, 22, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = Account(email="cleanup@example.com", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(
            account_id=account.id,
            name="Revoked token",
            token_prefix="vm_st_demo",
            token_hash="hash",
            status="revoked",
            revoked_at=now - timedelta(days=1),
            expires_at=now - timedelta(minutes=1),
        )
        session.add(token)
        await session.commit()

    async with session_factory() as session:
        updated = await sync_expired_tokens(session, account_id=1, now=now)

    async with session_factory() as session:
        token = await session.get(ServiceBearerToken, 1)
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert updated == 0
    assert token is not None
    assert token.status == "revoked"
    assert logs == []
