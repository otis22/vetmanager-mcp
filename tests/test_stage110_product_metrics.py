"""Stage 110: ad-hoc product metrics report."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from scripts.product_metrics_report import (
    _mask_email,
    collect_metrics,
    format_json,
    format_markdown,
)
from service_metrics import (
    record_business_event,
    reset_service_metrics,
    snapshot_service_metrics,
)
from storage_models import (
    ACCOUNT_STATUS_ACTIVE,
    Account,
    ServiceBearerToken,
    TOKEN_STATUS_ACTIVE,
    TOKEN_STATUS_REVOKED,
    TokenUsageLog,
    TokenUsageStat,
    VetmanagerConnection,
)
from auth_audit import (
    TOKEN_EVENT_AUTH_FAILED_EXPIRED,
    TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
    TOKEN_EVENT_AUTH_RATE_LIMITED,
    TOKEN_EVENT_AUTH_SUCCEEDED,
    TOKEN_EVENT_CREATED,
    TOKEN_EVENT_REVOKED,
)


# ── fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def now_utc() -> datetime:
    """Fixed 'now' used for all time windows in tests."""
    return datetime(2026, 4, 18, 12, 0, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def seeded_session(tmp_path: Path, sqlite_session_factory_builder, now_utc):
    """Seed an SQLite DB with fixture data covering every classification edge.

    Accounts:
    - A1 "live1@example.com"   — registered 60d ago, token used 3d ago  → live
    - A2 "live2@example.com"   — registered 10d ago, token used 1d ago  → live + new_30d + new_7d
    - A3 "dead@example.com"    — registered 60d ago, token used 40d ago → dead
    - A4 "new@example.com"     — registered 12h ago, no tokens          → new_24h + no_tokens
    - A5 "zombie@example.com"  — registered 40d ago, token NEVER used   → dead + has_tokens

    Tokens:
    - T1 → A1, active, never expires, last_used 3d ago (stat)
    - T2 → A2, active, expires in 5d, last_used 1d ago (stat)
    - T3 → A3, active, expires in 20d, last_used 40d ago (stat)
    - T4 → A5, active, never expires, no usage stat row
    - T5 → A1, revoked 2d ago (no usage stat)

    Logs (TokenUsageLog):
    - 6× TOKEN_EVENT_AUTH_SUCCEEDED over different windows:
      2 within 24h, +2 within 7d, +2 within 30d (6 total in 30d window)
    - 1× TOKEN_EVENT_CREATED at 12h ago (T4)
    - 1× TOKEN_EVENT_REVOKED at 2d ago (T5)
    - failures: 1× rate_limited 2h ago, 1× ip_denied 3d ago, 1× expired 10d ago
    """
    factory = await sqlite_session_factory_builder(tmp_path / "metrics.db")

    async with factory() as s:
        # Accounts
        a1 = Account(email="live1@example.com", password_hash="h", status=ACCOUNT_STATUS_ACTIVE,
                     created_at=now_utc - timedelta(days=60), updated_at=now_utc - timedelta(days=60))
        a2 = Account(email="live2@example.com", password_hash="h", status=ACCOUNT_STATUS_ACTIVE,
                     created_at=now_utc - timedelta(days=10), updated_at=now_utc - timedelta(days=10))
        a3 = Account(email="dead@example.com", password_hash="h", status=ACCOUNT_STATUS_ACTIVE,
                     created_at=now_utc - timedelta(days=60), updated_at=now_utc - timedelta(days=60))
        a4 = Account(email="new@example.com", password_hash="h", status=ACCOUNT_STATUS_ACTIVE,
                     created_at=now_utc - timedelta(hours=12), updated_at=now_utc - timedelta(hours=12))
        a5 = Account(email="zombie@example.com", password_hash="h", status=ACCOUNT_STATUS_ACTIVE,
                     created_at=now_utc - timedelta(days=40), updated_at=now_utc - timedelta(days=40))
        s.add_all([a1, a2, a3, a4, a5])
        await s.flush()

        # Connections (only A1, A2, A3 have active connection; A4, A5 none)
        for acc in (a1, a2, a3):
            s.add(VetmanagerConnection(
                account_id=acc.id, auth_mode="domain_api_key", status="active",
                created_at=now_utc - timedelta(days=30), updated_at=now_utc - timedelta(days=30),
            ))

        # Tokens
        t1 = ServiceBearerToken(account_id=a1.id, name="t1", token_prefix="sbt_t1",
                                token_hash="h1", status=TOKEN_STATUS_ACTIVE,
                                created_at=now_utc - timedelta(days=30))
        t2 = ServiceBearerToken(account_id=a2.id, name="t2", token_prefix="sbt_t2",
                                token_hash="h2", status=TOKEN_STATUS_ACTIVE,
                                expires_at=now_utc + timedelta(days=5),
                                created_at=now_utc - timedelta(days=5))
        t3 = ServiceBearerToken(account_id=a3.id, name="t3", token_prefix="sbt_t3",
                                token_hash="h3", status=TOKEN_STATUS_ACTIVE,
                                expires_at=now_utc + timedelta(days=20),
                                created_at=now_utc - timedelta(days=50))
        t4 = ServiceBearerToken(account_id=a5.id, name="t4", token_prefix="sbt_t4",
                                token_hash="h4", status=TOKEN_STATUS_ACTIVE,
                                created_at=now_utc - timedelta(hours=12))
        t5 = ServiceBearerToken(account_id=a1.id, name="t5", token_prefix="sbt_t5",
                                token_hash="h5", status=TOKEN_STATUS_REVOKED,
                                revoked_at=now_utc - timedelta(days=2),
                                created_at=now_utc - timedelta(days=5))
        s.add_all([t1, t2, t3, t4, t5])
        await s.flush()

        # Usage stats (only for tokens that have been used)
        s.add(TokenUsageStat(bearer_token_id=t1.id, request_count=50,
                             last_used_at=now_utc - timedelta(days=3)))
        s.add(TokenUsageStat(bearer_token_id=t2.id, request_count=120,
                             last_used_at=now_utc - timedelta(days=1)))
        s.add(TokenUsageStat(bearer_token_id=t3.id, request_count=10,
                             last_used_at=now_utc - timedelta(days=40)))

        # Logs — success events in various time windows
        for offset_hours in (2, 5, 30, 50, 250, 500):
            # 2h, 5h → 24h; 30h, 50h → 7d; 250h, 500h → 30d
            s.add(TokenUsageLog(
                bearer_token_id=t1.id, event_type=TOKEN_EVENT_AUTH_SUCCEEDED,
                event_at=now_utc - timedelta(hours=offset_hours),
            ))
        # Creation / revocation
        s.add(TokenUsageLog(bearer_token_id=t4.id, event_type=TOKEN_EVENT_CREATED,
                            event_at=now_utc - timedelta(hours=12)))
        s.add(TokenUsageLog(bearer_token_id=t5.id, event_type=TOKEN_EVENT_REVOKED,
                            event_at=now_utc - timedelta(days=2)))
        # Failures
        s.add(TokenUsageLog(bearer_token_id=t1.id, event_type=TOKEN_EVENT_AUTH_RATE_LIMITED,
                            event_at=now_utc - timedelta(hours=2)))
        s.add(TokenUsageLog(bearer_token_id=t3.id, event_type=TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
                            event_at=now_utc - timedelta(days=3)))
        s.add(TokenUsageLog(bearer_token_id=t2.id, event_type=TOKEN_EVENT_AUTH_FAILED_EXPIRED,
                            event_at=now_utc - timedelta(days=10)))

        await s.commit()

    return factory


# ── accounts counters ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_accounts_counters(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    a = m["accounts"]
    assert a["total"] == 5
    assert a["new_24h"] == 1          # A4
    assert a["new_7d"] == 1           # A4 (A2 is 10d — outside)
    assert a["new_30d"] == 2          # A4 + A2


@pytest.mark.asyncio
async def test_live_dead_classification(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    a = m["accounts"]
    # live = request within 7d: A1 (3d) + A2 (1d)
    assert a["live_7d"] == 2
    # dead = registered > 30d AND no request in 30d:
    #   A3 (last_used 40d ago, >30d) + A5 (registered 40d ago, token never used)
    # A1 made request 3d ago → not dead; A4 registered 12h ago → not old enough
    assert a["dead_30d"] == 2
    # no_tokens: A4 only
    assert a["no_tokens"] == 1
    # no_active_connection: A4 + A5
    assert a["no_active_connection"] == 2


# ── tokens counters ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_tokens_counters(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    t = m["tokens"]
    # active = status=active AND (no expiry OR expiry > now): T1, T2, T3, T4
    assert t["total_active"] == 4
    # expiring in 7d: T2 (expires in 5d)
    assert t["expiring_in_7d"] == 1
    # issued in 24h: T4 (via TOKEN_EVENT_CREATED 12h ago)
    assert t["issued_24h"] == 1
    # revoked in 24h: 0 (T5 revoked 2d ago — outside 24h window)
    assert t["revoked_24h"] == 0
    # revoked 7d: T5
    assert t["revoked_7d"] == 1


# ── requests + top accounts ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_requests_counters(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    r = m["requests"]
    # SUCCEEDED events: 2h, 5h (24h) + 30h, 50h (7d) + 250h, 500h (30d)
    assert r["total_24h"] == 2
    assert r["total_7d"] == 4
    assert r["total_30d"] == 6


@pytest.mark.asyncio
async def test_top_accounts_ranked(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=3)
    top = m["requests"]["top_accounts"]
    # Based on TokenUsageStat.request_count: A2=120, A1=50, A3=10
    assert len(top) == 3
    assert top[0]["request_count"] == 120
    assert top[0]["email"].startswith("li***")  # masked
    assert top[1]["request_count"] == 50
    assert top[2]["request_count"] == 10


# ── failures breakdown ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_failures_breakdown(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    f = m["failures"]
    assert f["by_event_24h"].get(TOKEN_EVENT_AUTH_RATE_LIMITED, 0) == 1
    assert f["by_event_24h"].get(TOKEN_EVENT_AUTH_FAILED_IP_DENIED, 0) == 0
    assert f["by_event_7d"].get(TOKEN_EVENT_AUTH_FAILED_IP_DENIED, 0) == 1
    assert f["by_event_7d"].get(TOKEN_EVENT_AUTH_RATE_LIMITED, 0) == 1
    assert f["by_event_30d"].get(TOKEN_EVENT_AUTH_FAILED_EXPIRED, 0) == 1


# ── dead accounts list ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dead_accounts_listed_with_masked_email(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=10)
    dead = m["accounts"]["dead_list"]
    emails = {d["email"] for d in dead}
    # Every email must be masked
    for e in emails:
        assert "***" in e, f"email not masked: {e}"
    assert len(dead) == 2  # A3 + A5


# ── email masking helper ───────────────────────────────────────────────────


def test_mask_email_short():
    assert _mask_email("a@b.com") == "***@***"  # too short to reveal safely


def test_mask_email_normal():
    assert _mask_email("alice@example.com") == "al***@ex***.com"


def test_mask_email_none():
    assert _mask_email(None) == "***"


# ── output formats ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_markdown_output_has_all_sections(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=5)
    md = format_markdown(m, now=now_utc, window_days=30)
    for header in (
        "# Product metrics",
        "## Accounts",
        "## Tokens",
        "## Requests",
        "## Failures",
        "## Dead accounts",
        "## Top accounts",
    ):
        assert header in md, f"missing section: {header!r}"


@pytest.mark.asyncio
async def test_json_output_stable_schema(seeded_session, now_utc):
    m = await collect_metrics(seeded_session, now=now_utc, window_days=30, top_n=5)
    out = format_json(m, now=now_utc, window_days=30)
    parsed = json.loads(out)
    assert set(parsed.keys()) >= {"accounts", "tokens", "requests", "failures",
                                  "generated_at", "window_days"}


# ── business events counter ────────────────────────────────────────────────


def test_record_business_event_increments_counter():
    reset_service_metrics()
    record_business_event("account_registered")
    record_business_event("account_registered")
    record_business_event("bearer_token_issued")
    snap = snapshot_service_metrics()
    assert snap["business_events_total"]["account_registered"] == 2
    assert snap["business_events_total"]["bearer_token_issued"] == 1
