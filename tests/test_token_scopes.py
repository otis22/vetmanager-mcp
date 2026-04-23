"""Unit tests for future bearer-token scope manifests."""

import json

import pytest

from service_token_service import issue_service_bearer_token
from storage_models import ServiceBearerToken
from token_scopes import (
    SCOPE_ADMISSIONS_READ,
    SCOPE_ADMISSIONS_WRITE,
    SCOPE_ANALYTICS_READ,
    SCOPE_CLIENTS_READ,
    SCOPE_CLIENTS_WRITE,
    SCOPE_FINANCE_READ,
    SCOPE_MESSAGING_WRITE,
    SCOPE_PETS_READ,
    SCOPE_PETS_WRITE,
    SCOPE_REFERENCE_READ,
    SCOPE_USERS_READ,
    SUPPORTED_TOKEN_SCOPES,
    TOKEN_ACCESS_POLICY_VERSION,
    deserialize_token_scopes,
    normalize_token_scopes,
)


def test_service_bearer_token_scope_helpers_roundtrip():
    token = ServiceBearerToken(account_id=1, name="Scoped token")

    token.set_scopes(["clients.read", "pets.write", "clients.read"])

    assert token.access_policy_version == TOKEN_ACCESS_POLICY_VERSION
    assert token.get_scopes() == ["clients.read", "pets.write"]
    assert json.loads(token.scopes_json or "[]") == ["clients.read", "pets.write"]
    assert bool(token.is_depersonalized) is False


def test_legacy_token_without_scopes_gets_full_access_defaults():
    token = ServiceBearerToken(account_id=1, name="Legacy token")

    assert token.get_scopes() == list(SUPPORTED_TOKEN_SCOPES)


def test_deserialize_missing_scopes_preserves_legacy_full_access():
    assert deserialize_token_scopes(None) == list(SUPPORTED_TOKEN_SCOPES)


def test_normalize_token_scopes_rejects_unknown_values():
    with pytest.raises(ValueError, match="Unknown token scopes"):
        normalize_token_scopes(["clients.read", "unknown.scope"])


@pytest.mark.asyncio
async def test_issue_service_bearer_token_persists_default_full_access_scopes(tmp_path):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from storage import Base, create_database_engine
    from storage_models import Account

    database_path = Path(tmp_path) / "token-scopes.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            account = Account(email="scopes@example.com", status="active")
            session.add(account)
            await session.commit()

        async with session_factory() as session:
            token, _ = await issue_service_bearer_token(
                session,
                account_id=1,
                name="Default access token",
                expires_in_days=7,
            )

        assert token.access_policy_version == TOKEN_ACCESS_POLICY_VERSION
        assert deserialize_token_scopes(token.scopes_json) == list(SUPPORTED_TOKEN_SCOPES)
        assert token.is_depersonalized is False
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_service_bearer_token_persists_depersonalized_policy_flag(tmp_path):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from storage import Base, create_database_engine
    from storage_models import Account

    database_path = Path(tmp_path) / "token-policy.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            account = Account(email="privacy@example.com", status="active")
            session.add(account)
            await session.commit()

        async with session_factory() as session:
            token, _ = await issue_service_bearer_token(
                session,
                account_id=1,
                name="Depersonalized token",
                expires_in_days=7,
                is_depersonalized=True,
            )

        assert token.is_depersonalized is True
        assert deserialize_token_scopes(token.scopes_json) == list(SUPPORTED_TOKEN_SCOPES)
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_issue_service_bearer_token_uses_selected_access_preset_scopes(tmp_path):
    from pathlib import Path

    from sqlalchemy.ext.asyncio import async_sessionmaker

    from storage import Base, create_database_engine
    from storage_models import Account

    database_path = Path(tmp_path) / "token-preset.db"
    engine = create_database_engine(f"sqlite:///{database_path}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            account = Account(email="preset@example.com", status="active")
            session.add(account)
            await session.commit()

        async with session_factory() as session:
            token, _ = await issue_service_bearer_token(
                session,
                account_id=1,
                name="Frontdesk token",
                access_preset="frontdesk",
            )

        assert deserialize_token_scopes(token.scopes_json) == [
            SCOPE_ADMISSIONS_READ,
            SCOPE_ADMISSIONS_WRITE,
            SCOPE_ANALYTICS_READ,
            SCOPE_CLIENTS_READ,
            SCOPE_CLIENTS_WRITE,
            SCOPE_FINANCE_READ,
            SCOPE_MESSAGING_WRITE,
            SCOPE_PETS_READ,
            SCOPE_PETS_WRITE,
            SCOPE_REFERENCE_READ,
            SCOPE_USERS_READ,
        ]
    finally:
        await engine.dispose()
