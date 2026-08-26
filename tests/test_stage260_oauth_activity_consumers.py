"""Stage 260: everything that answers "is this account active" must see both channels.

Writing the journal is only half the fix. The funnel, the silence gauge, the
account page and the reports each decided activity by looking at bearer tokens,
so an account working purely over OAuth stayed invisible — counted as never
having made a request, and shown "you haven't used it yet" in its own cabinet.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from activation_telemetry import reset_activation_telemetry_state, scan_activation_telemetry
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED
from service_metrics import snapshot_service_metrics
from storage_models import (
    Account,
    OAuthAccessToken,
    OAuthGrant,
    TokenUsageLog,
    VetmanagerConnection,
)

TEST_ENCRYPTION_KEY = "2M4BZ-HQ_z5oz8OnVwvj4zNQoBL8e50cdjOMoGlWifA="


@pytest_asyncio.fixture
async def session_factory(tmp_path: Path, sqlite_session_factory_builder):
    return await sqlite_session_factory_builder(tmp_path / "stage260-consumers.db")


@pytest.fixture(autouse=True)
def _reset_activation_state():
    reset_activation_telemetry_state()
    yield
    reset_activation_telemetry_state()


async def _seed_oauth_only_account(session, *, now: datetime, used_at: datetime | None):
    """An account that connected the clinic and works through OAuth, with no bearer token."""
    account = Account(email="oauth-only@example.com", status="active", created_at=now - timedelta(days=2))
    session.add(account)
    await session.flush()
    connection = VetmanagerConnection(
        account_id=account.id,
        auth_mode="domain_api_key",
        status="active",
        domain="oauth-only-clinic",
    )
    connection.set_credentials(
        {"domain": "oauth-only-clinic", "api_key": "key"},
        encryption_key=TEST_ENCRYPTION_KEY,
    )
    session.add(connection)
    await session.flush()
    grant = OAuthGrant(
        account_id=account.id,
        vetmanager_connection_id=connection.id,
        client_id="vm_oc_stage260",
        scopes_json='["clients.read"]',
        status="active",
        last_used_at=used_at,
    )
    session.add(grant)
    await session.flush()
    access_token = OAuthAccessToken(
        grant_id=grant.id,
        token_prefix="vm_oat_stage260",
        token_hash="hash-stage260",
        scope="clients.read",
        resource="https://test.example.com/mcp",
        status="active",
        expires_at=now + timedelta(hours=1),
        last_used_at=used_at,
    )
    session.add(access_token)
    await session.flush()
    if used_at is not None:
        session.add(
            TokenUsageLog(
                account_id=account.id,
                oauth_access_token_id=access_token.id,
                event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
                event_at=used_at,
            )
        )
    await session.commit()
    return account.id


@pytest.mark.asyncio
async def test_funnel_counts_oauth_only_account_as_having_made_a_request(session_factory):
    """`first_mcp_request` must not mean "made a request with a bearer token"."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        await _seed_oauth_only_account(session, now=now, used_at=now - timedelta(hours=1))

    async with session_factory() as session:
        await scan_activation_telemetry(session, now=now)

    funnel = snapshot_service_metrics()["activation_funnel_accounts"]
    assert funnel["first_mcp_request"] == 1
    assert funnel["with_recent_usage_7d"] == 1
    assert funnel["ready_for_mcp"] == 1


@pytest.mark.asyncio
async def test_silence_gauge_measures_oauth_account_from_its_last_request(session_factory):
    """An OAuth-only account had no gauge at all: the query started from bearer tokens."""
    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        account_id = await _seed_oauth_only_account(
            session, now=now, used_at=now - timedelta(hours=3)
        )

    async with session_factory() as session:
        await scan_activation_telemetry(session, now=now)

    gauges = snapshot_service_metrics()["account_last_request_age_hours"]
    # The snapshot keys accounts as strings — the gauge is a label, not an int.
    assert str(account_id) in gauges
    assert 2.5 <= gauges[str(account_id)] <= 3.5


@pytest.mark.asyncio
async def test_account_page_state_is_ready_for_oauth_only_account(session_factory, monkeypatch):
    """The cabinet told a working user to go make their first request."""
    import web_routes_account

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        account_id = await _seed_oauth_only_account(
            session, now=now, used_at=now - timedelta(minutes=5)
        )

    monkeypatch.setattr(web_routes_account, "get_session_factory", lambda: session_factory)
    state = await web_routes_account._load_activation_state_for_polling(account_id)
    assert state == "ready"


def test_rendered_activation_state_counts_oauth_usage():
    """First render goes through compute_activation_state, not the polling endpoint.

    Grant dicts arrive in the shape `web.py` builds them: a formatted string
    plus an ISO raw value, with "Never" standing for "connected but unused".
    """
    from web_html import compute_activation_state

    used_grant = {
        "status": "active",
        "last_used_at": "2026-08-26 07:54 UTC",
        "last_used_at_raw": "2026-08-26T07:54:00+00:00",
    }
    unused_grant = {"status": "active", "last_used_at": "Never", "last_used_at_raw": None}

    assert compute_activation_state(
        active_connection={"id": 1},
        integration_health_status="active",
        bearer_tokens=[],
        oauth_grants=[used_grant],
    ) == "ready"

    # A connected but never-used agent is still a step further than no access.
    assert compute_activation_state(
        active_connection={"id": 1},
        integration_health_status="active",
        bearer_tokens=[],
        oauth_grants=[unused_grant],
    ) == "needs_client_use"

    # No access of either kind stays "issue something first".
    assert compute_activation_state(
        active_connection={"id": 1},
        integration_health_status="active",
        bearer_tokens=[],
        oauth_grants=[],
    ) == "needs_token"


@pytest.mark.asyncio
async def test_product_report_counts_oauth_only_account_as_live(session_factory):
    """`dead_list` used to name accounts that had been calling all week."""
    from scripts.product_metrics_report import (
        _count_dead_accounts,
        _count_live_accounts,
        _fetch_dead_account_rows,
    )

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        account_id = await _seed_oauth_only_account(
            session, now=now, used_at=now - timedelta(days=1)
        )
        # Registered long ago, so it is old enough to qualify as dead.
        account = await session.get(Account, account_id)
        account.created_at = now - timedelta(days=60)
        await session.commit()

    async with session_factory() as session:
        live = await _count_live_accounts(session, now=now, window=timedelta(days=7))
        dead = await _count_dead_accounts(session, now=now)
        dead_rows = await _fetch_dead_account_rows(session, now=now)

    assert live == 1
    assert dead == 0
    assert dead_rows == []


@pytest.mark.asyncio
async def test_zombie_archiver_spares_oauth_only_account(session_factory, monkeypatch):
    """The archiver decided "never used" from bearer traces the account does not have."""
    import scripts.archive_zombie_accounts as archive

    now = datetime.now(timezone.utc)
    async with session_factory() as session:
        account_id = await _seed_oauth_only_account(
            session, now=now, used_at=now - timedelta(days=1)
        )
        account = await session.get(Account, account_id)
        account.created_at = now - timedelta(days=60)
        # Drop the connection: it is the only thing protecting such an account
        # today, and the protection should not depend on it.
        connection = await session.scalar(
            select(VetmanagerConnection).where(VetmanagerConnection.account_id == account_id)
        )
        connection.status = "disabled"
        await session.commit()

    monkeypatch.setattr(archive, "get_session_factory", lambda: session_factory)
    result = await archive.archive_zombie_accounts(apply=False, now=now)
    assert result["candidate_ids"] == []
