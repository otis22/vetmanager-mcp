"""Stage 260: authentication is journalled the same way on both access channels.

Until this stage `token_usage_logs` described bearer only, so every question
about who is active answered for half the users. These tests pin the new
contract: one row per authenticated request, whichever channel it arrived on,
carrying the account it belongs to.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import select

import auth.request as auth_request
import runtime_auth
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED
from bearer_token_manager import build_token_prefix, generate_bearer_token, hash_bearer_token
from storage_models import (
    Account,
    OAuthAccessToken,
    OAuthGrant,
    ServiceBearerToken,
    TokenUsageLog,
    VetmanagerConnection,
)

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="
OAUTH_RAW_ACCESS_TOKEN = "vm_oat_stage260_usage_log"


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "stage260-usage-log.db")


async def _seed_account(session, *, email: str, domain: str) -> tuple[Account, VetmanagerConnection]:
    account = Account(email=email, status="active")
    session.add(account)
    await session.flush()
    connection = VetmanagerConnection(
        account_id=account.id,
        auth_mode="domain_api_key",
        status="active",
        domain=domain,
    )
    connection.set_credentials(
        {"domain": domain, "api_key": f"{domain}-key"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )
    session.add(connection)
    await session.flush()
    return account, connection


async def _usage_rows(session_factory) -> list[TokenUsageLog]:
    async with session_factory() as session:
        return list(
            (
                await session.execute(
                    select(TokenUsageLog).order_by(TokenUsageLog.id)
                )
            ).scalars().all()
        )


@pytest.mark.asyncio
async def test_oauth_request_is_journalled_with_account_and_token(session_factory, monkeypatch):
    """An OAuth call must leave the same auth-success row a bearer call leaves."""
    monkeypatch.setenv("SITE_BASE_URL", "https://test.example.com")
    now = datetime.now(timezone.utc)

    async with session_factory() as session:
        account, connection = await _seed_account(
            session, email="oauth@example.com", domain="oauth-clinic"
        )
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id="vm_oc_test",
            scopes_json='["clients.read"]',
            is_depersonalized=False,
            status="active",
        )
        session.add(grant)
        await session.flush()
        access_token = OAuthAccessToken(
            grant_id=grant.id,
            token_prefix=build_token_prefix(OAUTH_RAW_ACCESS_TOKEN),
            token_hash=hash_bearer_token(OAUTH_RAW_ACCESS_TOKEN),
            scope="clients.read",
            resource="https://test.example.com/mcp",
            status="active",
            expires_at=now + timedelta(minutes=30),
        )
        session.add(access_token)
        await session.commit()
        account_id, access_token_id = account.id, access_token.id

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {OAUTH_RAW_ACCESS_TOKEN}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            await runtime_auth.resolve_runtime_credentials()

    rows = await _usage_rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.event_type == TOKEN_EVENT_AUTH_SUCCEEDED
    assert row.account_id == account_id
    assert row.oauth_access_token_id == access_token_id
    assert row.bearer_token_id is None


@pytest.mark.asyncio
async def test_bearer_request_is_journalled_with_account(session_factory, monkeypatch):
    """The bearer path keeps its row and now names the account on it."""
    raw_token = generate_bearer_token()

    async with session_factory() as session:
        account, _connection = await _seed_account(
            session, email="bearer@example.com", domain="bearer-clinic"
        )
        token = ServiceBearerToken(account_id=account.id, name="Cursor")
        token.set_raw_token(raw_token)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id

    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    headers = {"authorization": f"Bearer {raw_token}"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        with patch.object(runtime_auth, "get_session_factory", return_value=session_factory):
            await runtime_auth.resolve_runtime_credentials()

    rows = await _usage_rows(session_factory)
    success = [row for row in rows if row.event_type == TOKEN_EVENT_AUTH_SUCCEEDED]
    assert len(success) == 1
    assert success[0].account_id == account_id
    assert success[0].bearer_token_id == token_id
    assert success[0].oauth_access_token_id is None


@pytest.mark.asyncio
async def test_lifecycle_rows_also_carry_the_account(session_factory, monkeypatch):
    """Token creation is journalled too — a row without an account falls out of every aggregate."""
    from service_token_service import issue_service_bearer_token

    async with session_factory() as session:
        account, _connection = await _seed_account(
            session, email="lifecycle@example.com", domain="lifecycle-clinic"
        )
        await session.commit()
        account_id = account.id

    async with session_factory() as session:
        await issue_service_bearer_token(
            session,
            account_id=account_id,
            name="Claude",
            ip_mask="*.*.*.*",
        )

    rows = await _usage_rows(session_factory)
    assert rows, "token creation must be journalled"
    assert all(row.account_id == account_id for row in rows)
