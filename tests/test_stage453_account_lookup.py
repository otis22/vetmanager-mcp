"""Account attribution is a hash lookup, including known inactive credentials."""

from datetime import datetime, timedelta, timezone

import pytest

import mcp_transport_observation as observation
import storage
from bearer_token_manager import hash_bearer_token
from storage_models import Account, OAuthAccessToken, OAuthGrant, ServiceBearerToken


@pytest.mark.asyncio
async def test_lookup_maps_known_revoked_bearer_and_oauth_to_account(tmp_path, monkeypatch):
    database = tmp_path / "stage453.sqlite"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database}")
    storage.reset_storage_state()
    engine = storage.create_database_engine(f"sqlite:///{database}")
    async with engine.begin() as connection:
        await connection.run_sync(storage.Base.metadata.create_all)
    bearer = "vm_st_" + "b" * 43
    oauth = "vm_oat_" + "c" * 43
    async with storage.get_session_factory()() as session:
        account = Account(email="stage453@example.invalid")
        session.add(account)
        await session.flush()
        account_id = account.id
        session.add(ServiceBearerToken(account_id=account_id, name="test",
            token_prefix="stage453bear", token_hash=hash_bearer_token(bearer), status="revoked"))
        grant = OAuthGrant(account_id=account_id, vetmanager_connection_id=1,
                           client_id="stage453-client", scopes_json="[]", status="revoked")
        session.add(grant)
        await session.flush()
        session.add(OAuthAccessToken(grant_id=grant.id, token_prefix="stage453oauth",
            token_hash=hash_bearer_token(oauth), scope="", resource="https://example.invalid/mcp",
            status="revoked", expires_at=datetime.now(timezone.utc)-timedelta(days=1)))
        await session.commit()
    assert await observation._lookup_handshake_account(bearer, "service_bearer") == account_id
    assert await observation._lookup_handshake_account(oauth, "oauth_access") == account_id
    assert await observation._lookup_handshake_account("vm_oat_" + "d" * 43, "oauth_access") is None
    await engine.dispose()
    storage.reset_storage_state()
