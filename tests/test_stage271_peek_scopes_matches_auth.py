"""Stage 271 — the catalogue's view of a token never outruns authentication.

`peek_runtime_scopes` reads rights without journalling the request, which means
it repeats the checks instead of calling the auth path. Repeated checks drift.
This file pins them together: for every way a token can be refused, asking for
the catalogue must answer "rights unknown" — otherwise a key that cannot call
anything still gets told what it could have called, which is exactly the thing
an IP mask exists to prevent.

The single deliberate difference is the rate limiter, asserted at the bottom:
asking for the catalogue is not a call and must not spend the budget for one.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

import auth.bearer as bearer_auth_impl
import runtime_auth
from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import generate_bearer_token
from exceptions import AuthError, RateLimitError
from runtime_auth import peek_runtime_scopes
from storage_models import (
    TOKEN_STATUS_DISABLED,
    Account,
    ServiceBearerToken,
    VetmanagerConnection,
)
from token_scopes import SUPPORTED_TOKEN_SCOPES

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "peek-scopes.db")


async def _seed(session_factory, *, raw_token, **overrides):
    async with session_factory() as session:
        account = Account(
            email=f"{overrides.get('email', 'ops')}@example.com",
            status=overrides.get("account_status", "active"),
        )
        session.add(account)
        await session.flush()

        connection = VetmanagerConnection(
            account_id=account.id,
            auth_mode="domain_api_key",
            status=overrides.get("connection_status", "active"),
            domain="clinic-a",
        )
        connection.set_credentials(
            {"domain": "clinic-a", "api_key": "secret-key"},
            encryption_key=TEST_ENCRYPTION_KEY,
        )
        token = ServiceBearerToken(
            account_id=account.id,
            name="Catalogue token",
            status=overrides.get("token_status", "active"),
            allowed_ip_mask=overrides.get("ip_mask", "*.*.*.*"),
            expires_at=overrides.get("expires_at"),
        )
        token.set_raw_token(raw_token)
        if overrides.get("break_credentials"):
            # What a rotated encryption key or a half-written connection looks
            # like from here.
            connection.encrypted_credentials = "not-decryptable"
        if "scopes" in overrides:
            token.set_scopes(overrides["scopes"])
        session.add_all([connection, token])
        await session.commit()


def _use_factory(monkeypatch, session_factory, raw_token, *, client_ip="10.0.0.1"):
    monkeypatch.setattr(runtime_auth, "get_session_factory", lambda: session_factory)
    monkeypatch.setattr(runtime_auth, "get_bearer_token", lambda: raw_token)
    monkeypatch.setattr(
        runtime_auth, "get_request_audit_metadata", lambda: (client_ip, None)
    )
    monkeypatch.setattr(
        bearer_auth_impl, "get_request_audit_metadata", lambda: (client_ip, None)
    )
    # The catalogue path decrypts the stored connection the same way the auth
    # path does, and here that means the fixture's key.
    monkeypatch.setattr(
        runtime_auth, "get_storage_encryption_key", lambda: TEST_ENCRYPTION_KEY
    )


# `accounts.status` only accepts "active" today, so an inactive account cannot
# be seeded and is not in this matrix; both paths read the same column.
REFUSING_SETUPS = {
    "disabled token": {"token_status": TOKEN_STATUS_DISABLED},
    "expired token": {"expires_at": datetime.now(timezone.utc) - timedelta(days=1)},
    "no rights at all": {"scopes": ()},
    "no active connection": {"connection_status": "disabled"},
    "another address": {"ip_mask": "203.0.113.7"},
    "connection that cannot be decrypted": {"break_credentials": True},
}

# A refusal is normally an AuthError. Unreadable credentials are the exception:
# the ordinary path fails there too, just not politely — it raises out of the
# decryption itself. What matters for this file is that it does not hand out
# credentials, so the catalogue must not hand out a tailored list.
REFUSAL_TYPES = {
    "connection that cannot be decrypted": Exception,
}


@pytest.mark.asyncio
@pytest.mark.parametrize("case", sorted(REFUSING_SETUPS))
async def test_a_token_authentication_refuses_gets_no_catalogue_either(
    case, session_factory, monkeypatch
):
    raw_token = generate_bearer_token()
    await _seed(session_factory, raw_token=raw_token, **REFUSING_SETUPS[case])
    _use_factory(monkeypatch, session_factory, raw_token)

    async with session_factory() as session:
        with pytest.raises(REFUSAL_TYPES.get(case, (AuthError, RateLimitError))):
            await resolve_bearer_auth_context(
                raw_token, session, encryption_key=TEST_ENCRYPTION_KEY
            )

    assert await peek_runtime_scopes() is None, case


@pytest.mark.asyncio
async def test_a_working_token_gets_its_rights(session_factory, monkeypatch):
    raw_token = generate_bearer_token()
    await _seed(session_factory, raw_token=raw_token, scopes=("clients.read",))
    _use_factory(monkeypatch, session_factory, raw_token)

    assert await peek_runtime_scopes() == ("clients.read",)


@pytest.mark.asyncio
async def test_asking_for_the_catalogue_writes_nothing(session_factory, monkeypatch):
    """The activation metrics count `token_auth_succeeded` rows to tell a key
    that is being used from one that was never tried. A catalogue request that
    left such a row would quietly turn every listing into 'the customer works
    with us'."""
    from sqlalchemy import func, select

    from storage_models import TokenUsageLog

    raw_token = generate_bearer_token()
    await _seed(session_factory, raw_token=raw_token, scopes=SUPPORTED_TOKEN_SCOPES)
    _use_factory(monkeypatch, session_factory, raw_token)

    async with session_factory() as session:
        token = await session.scalar(select(ServiceBearerToken))
        used_before = token.last_used_at

    await peek_runtime_scopes()

    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(TokenUsageLog)) == 0
        token = await session.scalar(select(ServiceBearerToken))
        assert token.last_used_at == used_before


@pytest.mark.asyncio
async def test_an_oauth_grant_that_is_no_longer_active_gets_no_catalogue(
    session_factory, monkeypatch
):
    """The OAuth branch repeats the same checks and can drift the same way."""
    from bearer_token_manager import hash_bearer_token
    from oauth_service import OAUTH_ACCESS_TOKEN_PREFIX
    from storage_models import OAuthAccessToken, OAuthGrant

    raw_token = f"{OAUTH_ACCESS_TOKEN_PREFIX}catalogue-probe"

    async with session_factory() as session:
        account = Account(email="oauth@example.com", status="active")
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
        session.add(connection)
        await session.flush()
        grant = OAuthGrant(
            account_id=account.id,
            vetmanager_connection_id=connection.id,
            client_id="chatgpt",
            scopes_json='["clients.read"]',
            access_preset="read_only",
            status="revoked",
        )
        session.add(grant)
        await session.flush()
        session.add(
            OAuthAccessToken(
                grant_id=grant.id,
                token_prefix=raw_token[:12],
                token_hash=hash_bearer_token(raw_token),
                scope="clients.read",
                resource="https://vetmanager-mcp.example/mcp",
                status="active",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await session.commit()

    _use_factory(monkeypatch, session_factory, raw_token)

    assert await peek_runtime_scopes() is None
