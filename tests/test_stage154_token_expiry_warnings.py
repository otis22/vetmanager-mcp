"""Stage 154 — Token expiry pre-notification.

Tests for `scan_token_expiry_warnings`: 14/7/1-day thresholds with
exact-match dedup via 3 distinct event_types, business event counter
per threshold, privacy whitelist on details payload.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

import service_metrics
from auth_audit import (
    TOKEN_EVENT_EXPIRY_WARNING_1,
    TOKEN_EVENT_EXPIRY_WARNING_7,
    TOKEN_EVENT_EXPIRY_WARNING_14,
)
from storage_models import (
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TOKEN_STATUS_DISABLED,
    TOKEN_STATUS_EXPIRED,
    TOKEN_STATUS_REVOKED,
    TokenUsageLog,
)
from token_cleanup import scan_token_expiry_warnings

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── helpers ─────────────────────────────────────────────────────────────────


async def _make_account(session, *, email: str = "test@example.com") -> Account:
    account = Account(
        email=email,
        password_hash="x",
        status="active",
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


_TOKEN_COUNTER = {"n": 0}


async def _make_token(
    session,
    *,
    account_id: int,
    expires_at: datetime | None,
    status: str = TOKEN_STATUS_ACTIVE,
    name: str = "test-token",
) -> ServiceBearerToken:
    _TOKEN_COUNTER["n"] += 1
    suffix = _TOKEN_COUNTER["n"]
    token = ServiceBearerToken(
        account_id=account_id,
        name=name,
        token_prefix=f"sbt_test_{suffix:04d}",
        token_hash=f"hash_{suffix:04d}_" + "x" * 50,
        status=status,
        expires_at=expires_at,
    )
    session.add(token)
    await session.commit()
    await session.refresh(token)
    return token


async def _warning_rows(session, token_id: int) -> list[TokenUsageLog]:
    rows = (
        await session.execute(
            select(TokenUsageLog)
            .where(TokenUsageLog.bearer_token_id == token_id)
            .where(TokenUsageLog.event_type.in_([
                TOKEN_EVENT_EXPIRY_WARNING_1,
                TOKEN_EVENT_EXPIRY_WARNING_7,
                TOKEN_EVENT_EXPIRY_WARNING_14,
            ]))
        )
    ).scalars().all()
    return list(rows)


@pytest.fixture
def reset_metrics():
    service_metrics.reset_service_metrics()
    yield
    service_metrics.reset_service_metrics()


# ─── AC #1, #2: constants + business event allowlist ─────────────────────────


def test_ac1_constants_have_expected_values() -> None:
    assert TOKEN_EVENT_EXPIRY_WARNING_1 == "token_expiry_warning_1d"
    assert TOKEN_EVENT_EXPIRY_WARNING_7 == "token_expiry_warning_7d"
    assert TOKEN_EVENT_EXPIRY_WARNING_14 == "token_expiry_warning_14d"


def test_ac2_business_event_allowlist_includes_per_threshold() -> None:
    allowed = service_metrics._ALLOWED_BUSINESS_EVENTS
    assert "token_expiry_warning_1d" in allowed
    assert "token_expiry_warning_7d" in allowed
    assert "token_expiry_warning_14d" in allowed


# ─── AC #3, #4: detection rule ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac4_token_at_13d_emits_threshold_14(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "a.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=13))

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert [r.event_type for r in rows] == [TOKEN_EVENT_EXPIRY_WARNING_14]


@pytest.mark.asyncio
async def test_ac4_days_5_no_prior_emits_threshold_7_not_1(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    """Selection rule: min(crossed - emitted) — for days=5, crossed={7,14}, no prior → emit 7 (not 1)."""
    session_factory = await sqlite_session_factory_builder(tmp_path / "b.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=5))

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert [r.event_type for r in rows] == [TOKEN_EVENT_EXPIRY_WARNING_7]


@pytest.mark.asyncio
async def test_ac4_days_5_with_prior_14_still_emits_7(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "c.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=13))

    # First scan emits 14
    async with session_factory() as session:
        await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    # Token now closer to expiry (5 days left)
    new_now = now + timedelta(days=8)  # token at expires_at = now+13d, so now+8d → 5 days remaining
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=new_now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    types = {r.event_type for r in rows}
    assert types == {TOKEN_EVENT_EXPIRY_WARNING_14, TOKEN_EVENT_EXPIRY_WARNING_7}


@pytest.mark.asyncio
async def test_ac4_under_one_day_with_prior_7_14_emits_1(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "d.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        # ~12h to expiry → ceil → days_to_expiry=1
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(hours=12))

    # Pre-seed prior warnings for 7 and 14
    from auth_audit import add_token_usage_log
    async with session_factory() as session:
        for et in (TOKEN_EVENT_EXPIRY_WARNING_7, TOKEN_EVENT_EXPIRY_WARNING_14):
            add_token_usage_log(
                session,
                bearer_token_id=token.id,
                event_type=et,
                details={"account_id": account.id, "token_prefix": token.token_prefix},
            )
        await session.commit()

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    types = sorted(r.event_type for r in rows)
    assert TOKEN_EVENT_EXPIRY_WARNING_1 in types


# ─── AC #4: boundary semantics ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac4_boundary_exactly_7_days_treated_as_crossed(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "e.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=7))

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert [r.event_type for r in rows] == [TOKEN_EVENT_EXPIRY_WARNING_7]


@pytest.mark.asyncio
async def test_ac4_boundary_just_over_7_days_only_14_crossed(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "f.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(
            session, account_id=account.id,
            expires_at=now + timedelta(days=7, milliseconds=1),
        )

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert emitted == 1
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert [r.event_type for r in rows] == [TOKEN_EVENT_EXPIRY_WARNING_14]


# ─── AC #5: dedup ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac5_repeat_scan_same_threshold_no_duplicate(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "g.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=10))

    async with session_factory() as session:
        first = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    async with session_factory() as session:
        second = await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    assert first == 1
    assert second == 0
    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert len(rows) == 1


# ─── AC #7: filter ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac7_revoked_token_skipped(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "h.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session)
        token = await _make_token(
            session, account_id=account.id,
            expires_at=now + timedelta(days=5),
            status=TOKEN_STATUS_REVOKED,
        )
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 0


@pytest.mark.asyncio
async def test_ac7_already_expired_token_skipped(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "i.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session)
        await _make_token(
            session, account_id=account.id,
            expires_at=now - timedelta(days=1),
            status=TOKEN_STATUS_EXPIRED,
        )
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 0


@pytest.mark.asyncio
async def test_ac7_disabled_token_skipped(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "j.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session)
        await _make_token(
            session, account_id=account.id,
            expires_at=now + timedelta(days=5),
            status=TOKEN_STATUS_DISABLED,
        )
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 0


@pytest.mark.asyncio
async def test_ac7_token_without_expires_at_skipped(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "k.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session)
        await _make_token(session, account_id=account.id, expires_at=None)
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 0


@pytest.mark.asyncio
async def test_ac7_token_far_future_skipped(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "l.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session)
        await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=30))
    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 0


# ─── AC #8: business event counter ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac8_business_event_counter_increments_per_threshold(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "m.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)

    async with session_factory() as session:
        account = await _make_account(session)
        await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=13), name="t14")
        await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=5), name="t7")

    async with session_factory() as session:
        emitted = await scan_token_expiry_warnings(session, account_id=account.id, now=now)
    assert emitted == 2

    snapshot = service_metrics.snapshot_service_metrics()["business_events_total"]
    assert snapshot.get("token_expiry_warning_14d") == 1
    assert snapshot.get("token_expiry_warning_7d") == 1
    assert snapshot.get("token_expiry_warning_1d", 0) == 0


# ─── AC #6: privacy whitelist ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac6_details_payload_contains_only_whitelisted_fields(
    sqlite_session_factory_builder, tmp_path, reset_metrics,
) -> None:
    session_factory = await sqlite_session_factory_builder(tmp_path / "n.db")
    now = datetime(2026, 5, 2, 12, 0, 0, tzinfo=timezone.utc)
    async with session_factory() as session:
        account = await _make_account(session, email="leaky@example.com")
        token = await _make_token(session, account_id=account.id, expires_at=now + timedelta(days=5))
    async with session_factory() as session:
        await scan_token_expiry_warnings(session, account_id=account.id, now=now)

    async with session_factory() as session:
        rows = await _warning_rows(session, token.id)
    assert len(rows) == 1
    payload = json.loads(rows[0].details_json)
    # Email must NOT appear anywhere
    assert "leaky@example.com" not in rows[0].details_json
    # Whitelist of payload keys (allow request_id/correlation_id added by add_token_usage_log)
    expected_keys = {"account_id", "token_prefix", "threshold_days", "days_to_expiry", "expires_at_utc"}
    payload_keys = set(payload.keys()) - {"request_id", "correlation_id"}
    assert payload_keys == expected_keys
    # expires_at_utc parses back as UTC-aware
    parsed = datetime.fromisoformat(payload["expires_at_utc"])
    assert parsed.tzinfo is not None


# ─── AC #9: web.py integration smoke ──────────────────────────────────────────


def test_ac9_web_dashboard_calls_scan_token_expiry_warnings() -> None:
    text = (REPO_ROOT / "web.py").read_text(encoding="utf-8")
    assert "scan_token_expiry_warnings" in text, (
        "AC #9: web.py dashboard route must invoke scan_token_expiry_warnings"
    )
