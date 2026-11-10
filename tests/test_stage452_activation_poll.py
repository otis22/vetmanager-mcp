"""Этап 452: страница и опрос учитывают только действующий доступ."""

from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

import storage
import web
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED
from bearer_auth import resolve_bearer_auth_context
from bearer_token_manager import generate_bearer_token
from storage_models import OAuthAccessToken, OAuthGrant, ServiceBearerToken, TokenUsageLog
from tests.test_stage197_token_quick_issue import _account_page, _app_client, _token_view
from tests.test_stage260_oauth_activity_consumers import _seed_oauth_only_account, TEST_ENCRYPTION_KEY
from tests.test_web_auth import _prepare_web_db
from web_auth import SESSION_COOKIE_NAME, create_account_session_token


@pytest_asyncio.fixture
async def account_db(tmp_path, monkeypatch):
    engine = await _prepare_web_db(tmp_path, monkeypatch)
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", TEST_ENCRYPTION_KEY)
    now = datetime.now(timezone.utc)
    async with storage.get_session_factory()() as session:
        account_id = await _seed_oauth_only_account(session, now=now, used_at=None)
    try:
        yield account_id, now
    finally:
        await engine.dispose()
        storage.reset_storage_state()


async def _states(account_id, monkeypatch):
    async def health(*args, **kwargs):
        return "active", "ok"

    monkeypatch.setattr(web, "evaluate_connection_health", health)
    async with _app_client() as client:
        client.cookies.set(SESSION_COOKIE_NAME, create_account_session_token(account_id))
        page = await client.get("/account")
        assert page.status_code == 200

        async def no_probe(*args, **kwargs):
            pytest.fail("Опрос не должен обращаться к проверке upstream")

        monkeypatch.setattr(web, "evaluate_connection_health", no_probe)
        poll = await client.get("/account/activation-status")
        assert poll.status_code == 200
        state = poll.json()["state"]
        assert f'data-activation-state="{state}"' in page.text
        return state


@pytest.mark.asyncio
@pytest.mark.parametrize("old_status", ["revoked", "expired", "active"])
async def test_old_bearer_usage_does_not_activate_new_key(account_db, monkeypatch, old_status):
    account_id, now = account_db
    fresh_raw = generate_bearer_token()
    async with storage.get_session_factory()() as session:
        grant = await session.scalar(select(OAuthGrant))
        grant.status = "revoked"
        old = ServiceBearerToken(account_id=account_id, name="452-old", status=old_status,
                                 expires_at=now + timedelta(days=1) if old_status == "revoked" else now - timedelta(seconds=1),
                                 last_used_at=now)
        old.set_raw_token(generate_bearer_token())
        fresh = ServiceBearerToken(account_id=account_id, name="452-new", status="active")
        fresh.set_raw_token(fresh_raw)
        session.add_all([old, fresh])
        await session.flush()
        session.add(TokenUsageLog(account_id=account_id, bearer_token_id=old.id,
                                  event_type=TOKEN_EVENT_AUTH_SUCCEEDED, event_at=now))
        await session.commit()
    assert await _states(account_id, monkeypatch) == "needs_client_use"
    async with storage.get_session_factory()() as session:
        await resolve_bearer_auth_context(fresh_raw, session,
                                          encryption_key=TEST_ENCRYPTION_KEY)
        await session.execute(delete(TokenUsageLog))
        await session.commit()
    assert await _states(account_id, monkeypatch) == "ready"


@pytest.mark.asyncio
async def test_oauth_usage_belongs_to_live_grant(account_db, monkeypatch):
    account_id, now = account_db
    assert await _states(account_id, monkeypatch) == "needs_client_use"
    async with storage.get_session_factory()() as session:
        used = await session.scalar(select(OAuthGrant))
        used.last_used_at = now
        await session.commit()
    assert await _states(account_id, monkeypatch) == "ready"
    async with storage.get_session_factory()() as session:
        access = await session.scalar(select(OAuthAccessToken))
        access.expires_at = now - timedelta(seconds=1)
        fresh = OAuthGrant(account_id=account_id, client_id=used.client_id,
                           vetmanager_connection_id=used.vetmanager_connection_id,
                           scopes_json=used.scopes_json, status="active")
        session.add(fresh)
        await session.flush()
        session.add(OAuthAccessToken(grant_id=fresh.id, token_prefix="452-new",
                                    token_hash="452-new", scope=access.scope,
                                    resource=access.resource, status="active",
                                    expires_at=now + timedelta(hours=1)))
        await session.commit()
    assert await _states(account_id, monkeypatch) == "needs_client_use"


def test_iso_expiry_preserves_seconds():
    now = datetime(2026, 11, 10, 12, 34, 10, tzinfo=timezone.utc)
    token = _token_view(expires_at_raw="2026-11-10T12:34:50+00:00",
                        expires_at="2026-11-10 12:34 UTC")
    html = _account_page(bearer_tokens=[token], activation_now=now)
    assert 'data-activation-state="needs_client_use"' in html
    assert 'data-poll-activation="needs_client_use"' in html


def test_unhealthy_page_does_not_poll():
    html = _account_page(bearer_tokens=[_token_view()], integration_health_status="unknown")
    assert 'data-activation-state="needs_connection"' in html
    assert 'data-poll-activation="' not in html
