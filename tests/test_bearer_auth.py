"""Unit tests for stage 22.2 bearer token lookup."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import generate_bearer_token
from exceptions import AuthError, RateLimitError
from storage_models import Account, ServiceBearerToken, TokenUsageLog, TokenUsageStat, VetmanagerConnection
from vetmanager_auth import VETMANAGER_AUTH_MODE_USER_TOKEN


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "bearer-auth.db")


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_returns_active_account_and_connection(session_factory):
    """Lookup should resolve token -> account -> active Vetmanager connection."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="clinic-a",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        context = await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    assert context.account_id == account.id
    assert context.connection_id == connection.id
    assert context.bearer_token_id == token.id
    assert context.auth_mode == "domain_api_key"
    assert context.domain == "clinic-a"
    assert context.api_key == "secret-key"


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_returns_normalized_credentials_for_user_token_mode(
    session_factory,
):
    """Bearer runtime should expose the same normalized context for user_token mode."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode=VETMANAGER_AUTH_MODE_USER_TOKEN,
            status="active",
            domain="clinic-user",
        )
        connection.set_credentials(
            {"domain": "clinic-user", "user_token": "user-token-secret"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        context = await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    assert context.account_id == account.id
    assert context.connection_id == connection.id
    assert context.bearer_token_id == token.id
    assert context.auth_mode == VETMANAGER_AUTH_MODE_USER_TOKEN
    assert context.domain == "clinic-user"
    assert context.api_key == "user-token-secret"


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_updates_last_used_at_for_active_token(session_factory):
    """Successful bearer resolution should stamp last_used_at for usage accounting."""
    raw_token = generate_bearer_token()
    used_at = datetime(2026, 3, 21, 12, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="clinic-a",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
            now=used_at,
        )

    async with session_factory() as session:
        stored = await session.get(ServiceBearerToken, 1)

    assert stored is not None
    assert stored.last_used_at is not None
    assert stored.last_used_at.replace(tzinfo=timezone.utc) == used_at


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_increments_request_count(session_factory):
    """Successful bearer resolution should create/update usage stats request count."""
    raw_token = generate_bearer_token()
    used_at = datetime(2026, 3, 21, 12, 5, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="clinic-a",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
            now=used_at,
        )
    async with session_factory() as session:
        await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
            now=used_at,
        )

    async with session_factory() as session:
        stats = await session.scalar(
            select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == 1)
        )

    assert stats is not None
    assert stats.request_count == 2
    assert stats.last_used_at is not None
    assert stats.last_used_at.replace(tzinfo=timezone.utc) == used_at


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_writes_success_audit_log(session_factory):
    """Successful bearer auth should append a token auth audit event."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
            domain="clinic-a",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        await resolve_bearer_auth_context(
            raw_token,
            session,
            encryption_key=TEST_ENCRYPTION_KEY,
        )

    async with session_factory() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert [log.event_type for log in logs] == ["token_auth_succeeded"]
    assert "secret-key" not in (logs[0].details_json or "")
    assert "clinic-a" in (logs[0].details_json or "")


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_rejects_revoked_token(session_factory):
    """Lookup should reject revoked bearer tokens."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        token.revoke()
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Revoked bearer"):
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    async with session_factory() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert [log.event_type for log in logs] == ["token_auth_failed_revoked"]


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_rejects_invalid_token(session_factory):
    """Lookup should fail safely for unknown bearer token."""
    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid bearer"):
            await resolve_bearer_auth_context(
                "vm_st_nonexistent_token",
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_rejects_expired_token(session_factory):
    """Lookup should reject expired bearer tokens."""
    from datetime import datetime, timedelta, timezone

    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="active",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(
            account_id=account.id,
            name="Cursor token",
            expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Expired bearer"):
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    async with session_factory() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert [log.event_type for log in logs] == ["token_auth_failed_expired"]


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_requires_active_connection(session_factory):
    """Lookup should fail when account has no active Vetmanager connection."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account = Account(email="ops@example.com", status="active")
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status="disabled",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor token")
        token.set_raw_token(raw_token)
        session.add_all([connection, token])
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Account connection not configured"):
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
            )

    async with session_factory() as session:
        logs = (
            await session.execute(
                select(TokenUsageLog)
                .where(TokenUsageLog.bearer_token_id == 1)
                .order_by(TokenUsageLog.id.asc())
            )
        ).scalars().all()

    assert [log.event_type for log in logs] == ["token_auth_failed_no_connection"]


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_writes_rate_limit_audit_log(session_factory, monkeypatch):
    """Rate-limited bearer auth should append a dedicated audit event."""
    import bearer_rate_limiter

    raw_token = generate_bearer_token()
    used_at = datetime(2026, 3, 21, 12, 45, tzinfo=timezone.utc)
    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "1")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "60")
    bearer_rate_limiter.reset_bearer_rate_limiter()

    try:
        async with session_factory() as session:
            account = Account(email="ops@example.com", status="active")
            session.add(account)
            await session.flush()

            connection = VetmanagerConnection(
                account_id=account.id,
                auth_mode="domain_api_key",
                status="active",
                domain="clinic-a",
            )
            connection.set_credentials(
                {"domain": "clinic-a", "api_key": "secret-key"},
                encryption_key=TEST_ENCRYPTION_KEY,
            )
            token = ServiceBearerToken(account_id=account.id, name="Cursor token")
            token.set_raw_token(raw_token)
            session.add_all([connection, token])
            await session.commit()

        async with session_factory() as session:
            await resolve_bearer_auth_context(
                raw_token,
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
                now=used_at,
            )
        async with session_factory() as session:
            with pytest.raises(RateLimitError, match="rate limit exceeded"):
                await resolve_bearer_auth_context(
                    raw_token,
                    session,
                    encryption_key=TEST_ENCRYPTION_KEY,
                    now=used_at,
                )

        async with session_factory() as session:
            logs = (
                await session.execute(
                    select(TokenUsageLog)
                    .where(TokenUsageLog.bearer_token_id == 1)
                    .order_by(TokenUsageLog.id.asc())
                )
            ).scalars().all()
    finally:
        bearer_rate_limiter.reset_bearer_rate_limiter()

    assert [log.event_type for log in logs] == [
        "token_auth_succeeded",
        "token_auth_rate_limited",
    ]
    assert "retry_after_seconds" in (logs[-1].details_json or "")
