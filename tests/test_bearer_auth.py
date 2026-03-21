"""Unit tests for stage 22.2 bearer token lookup."""

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker

from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import generate_bearer_token
from exceptions import AuthError
from storage import Base, create_database_engine
from storage_models import Account, ServiceBearerToken, VetmanagerConnection


TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


async def _make_session_factory(tmp_path: Path) -> async_sessionmaker:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'bearer-auth.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_returns_active_account_and_connection(tmp_path: Path):
    """Lookup should resolve token -> account -> active Vetmanager connection."""
    session_factory = await _make_session_factory(tmp_path)
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
async def test_resolve_bearer_auth_context_rejects_revoked_token(tmp_path: Path):
    """Lookup should reject revoked bearer tokens."""
    session_factory = await _make_session_factory(tmp_path)
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


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_rejects_invalid_token(tmp_path: Path):
    """Lookup should fail safely for unknown bearer token."""
    session_factory = await _make_session_factory(tmp_path)

    async with session_factory() as session:
        with pytest.raises(AuthError, match="Invalid bearer"):
            await resolve_bearer_auth_context(
                "vm_st_nonexistent_token",
                session,
                encryption_key=TEST_ENCRYPTION_KEY,
            )


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_rejects_expired_token(tmp_path: Path):
    """Lookup should reject expired bearer tokens."""
    from datetime import datetime, timedelta, timezone

    session_factory = await _make_session_factory(tmp_path)
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


@pytest.mark.asyncio
async def test_resolve_bearer_auth_context_requires_active_connection(tmp_path: Path):
    """Lookup should fail when account has no active Vetmanager connection."""
    session_factory = await _make_session_factory(tmp_path)
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
