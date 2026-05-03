"""Stage 155 — IP mask UX & restrictive default.

Verifies migration backfill + NOT NULL, removal of get_allowed_ip_mask
dual-API, explicit ip_mask service contract, ip_denied audit log
privacy payload, and shared privacy_utils helpers.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import inspect, text

REPO_ROOT = Path(__file__).resolve().parent.parent


# ─── AC #2: model — get_allowed_ip_mask removed, allowed_ip_mask non-optional ─


def test_ac2_model_drops_get_allowed_ip_mask_method() -> None:
    from storage_models import ServiceBearerToken
    assert not hasattr(ServiceBearerToken, "get_allowed_ip_mask"), (
        "AC #2: ServiceBearerToken.get_allowed_ip_mask must be removed"
    )


def test_ac2_model_allowed_ip_mask_not_nullable() -> None:
    from storage_models import ServiceBearerToken
    col = ServiceBearerToken.__table__.columns["allowed_ip_mask"]
    assert col.nullable is False, "AC #2: allowed_ip_mask must be NOT NULL"


# ─── AC #5: grep across project — no `get_allowed_ip_mask` left ──────────────


def test_ac5_grep_no_get_allowed_ip_mask_in_project() -> None:
    """All *.py (production + tests) must not reference removed helper.

    Allowed mentions:
      - this test file (asserts the absence — must literally name the symbol);
      - the Stage 155 migration (historical comment explaining the backfill).
    """
    import subprocess
    result = subprocess.run(
        [
            "grep", "-rn", "--include=*.py",
            "--exclude=test_stage155_ip_mask_restrictive_default.py",
            "--exclude=20260503_000013_allowed_ip_mask_not_null.py",
            "get_allowed_ip_mask", str(REPO_ROOT),
        ],
        capture_output=True, text=True,
    )
    # grep returns 1 when no matches — that is success here.
    matches = [
        line for line in result.stdout.splitlines()
        if "/__pycache__/" not in line
    ]
    assert matches == [], (
        "AC #5: get_allowed_ip_mask references must be deleted; found:\n" + "\n".join(matches)
    )


# ─── AC #1: migration round-trip + backfill ──────────────────────────────────


def test_ac1_migration_round_trip_backfills_null_to_wildcard(tmp_path: Path) -> None:
    """Stage 155 migration: NULL allowed_ip_mask backfilled to '*.*.*.*' + NOT NULL."""
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    import storage

    config = Config(str(REPO_ROOT / "alembic.ini"))
    db_url = f"sqlite:///{tmp_path / 'm.db'}"
    config.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        storage.normalize_database_url_for_migrations(db_url),
    )

    # Walk to the revision BEFORE the new Stage 155 migration so we can
    # insert a NULL-mask row first (mirrors prod state).
    command.upgrade(config, "20260502_000012")

    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.connect() as conn:
        conn.execute(text(
            "INSERT INTO accounts (email, password_hash, status, created_at, updated_at) "
            "VALUES ('legacy@example.com', 'h', 'active', datetime('now'), datetime('now'))"
        ))
        conn.execute(text(
            "INSERT INTO service_bearer_tokens "
            "(account_id, name, token_prefix, token_hash, status, allowed_ip_mask, created_at) "
            "VALUES (1, 'legacy', 'sbt_pre155', 'h' || hex(randomblob(28)), 'active', NULL, datetime('now'))"
        ))
        conn.commit()

    # Run the new migration.
    command.upgrade(config, "head")

    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT name, allowed_ip_mask FROM service_bearer_tokens WHERE name='legacy'"
        )).fetchall()
    assert rows == [("legacy", "*.*.*.*")], "AC #1: NULL backfilled to wildcard"

    # NOT NULL is enforced — try inserting another NULL.
    with engine.connect() as conn:
        with pytest.raises(Exception):
            conn.execute(text(
                "INSERT INTO service_bearer_tokens "
                "(account_id, name, token_prefix, token_hash, status, allowed_ip_mask, created_at) "
                "VALUES (1, 'after-migration', 'sbt_post155', 'hash_post', 'active', NULL, datetime('now'))"
            ))
            conn.commit()


# ─── AC #3, AC #4: service layer ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ac3_issue_service_bearer_token_requires_explicit_ip_mask(
    sqlite_session_factory_builder, tmp_path,
) -> None:
    """ip_mask is now positional — calling without it raises TypeError."""
    from service_token_service import issue_service_bearer_token
    from storage_models import Account

    session_factory = await sqlite_session_factory_builder(tmp_path / "ac3.db")
    async with session_factory() as session:
        account = Account(email="ac3@example.com", password_hash="x", status="active")
        session.add(account)
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(TypeError):
            await issue_service_bearer_token(  # type: ignore[call-arg]
                session,
                account_id=1,
                name="missing-ip",
                expires_in_days=30,
            )


@pytest.mark.asyncio
async def test_ac4_wildcard_ip_mask_persisted_explicitly_not_null(
    sqlite_session_factory_builder, tmp_path,
) -> None:
    """Wildcard mask is stored as the literal string, not NULL."""
    from service_token_service import issue_service_bearer_token
    from storage_models import Account, ServiceBearerToken
    from sqlalchemy import select

    session_factory = await sqlite_session_factory_builder(tmp_path / "ac4.db")
    async with session_factory() as session:
        account = Account(email="ac4@example.com", password_hash="x", status="active")
        session.add(account)
        await session.commit()

    async with session_factory() as session:
        await issue_service_bearer_token(
            session,
            account_id=1,
            name="explicit-wildcard",
            expires_in_days=30,
            ip_mask="*.*.*.*",
        )

    async with session_factory() as session:
        token = (await session.execute(
            select(ServiceBearerToken).where(ServiceBearerToken.name == "explicit-wildcard")
        )).scalar_one()
    assert token.allowed_ip_mask == "*.*.*.*", "AC #4: wildcard stored explicitly, not NULL"


@pytest.mark.asyncio
async def test_ac4_specific_ip_mask_persisted_unchanged(
    sqlite_session_factory_builder, tmp_path,
) -> None:
    from service_token_service import issue_service_bearer_token
    from storage_models import Account, ServiceBearerToken
    from sqlalchemy import select

    session_factory = await sqlite_session_factory_builder(tmp_path / "ac4b.db")
    async with session_factory() as session:
        session.add(Account(email="ac4b@example.com", password_hash="x", status="active"))
        await session.commit()

    async with session_factory() as session:
        await issue_service_bearer_token(
            session,
            account_id=1,
            name="specific",
            expires_in_days=30,
            ip_mask="192.168.1.42",
        )

    async with session_factory() as session:
        token = (await session.execute(
            select(ServiceBearerToken).where(ServiceBearerToken.name == "specific")
        )).scalar_one()
    assert token.allowed_ip_mask == "192.168.1.42"


# ─── AC #7: privacy_utils shared module ──────────────────────────────────────


def test_privacy_utils_mask_email_basic() -> None:
    from privacy_utils import mask_email
    assert mask_email("alice@example.com") == "al***@ex***.com"
    assert mask_email("a@b.com") == "***@***"
    assert mask_email(None) == "***"
    assert mask_email("") == "***"
    assert mask_email("invalid-email") == "***"


def test_privacy_utils_extract_client_ip_tail_ipv4() -> None:
    from privacy_utils import extract_client_ip_tail
    assert extract_client_ip_tail("192.168.1.5") == "5"
    assert extract_client_ip_tail("10.0.0.255") == "255"


def test_privacy_utils_extract_client_ip_tail_ipv6() -> None:
    from privacy_utils import extract_client_ip_tail
    assert extract_client_ip_tail("::1") == "1"
    assert extract_client_ip_tail("2001:db8::42") == "42"


def test_privacy_utils_extract_client_ip_tail_unknown() -> None:
    from privacy_utils import extract_client_ip_tail
    assert extract_client_ip_tail(None) == "unknown"
    assert extract_client_ip_tail("") == "unknown"
    assert extract_client_ip_tail("unknown") == "unknown"


def test_product_metrics_report_uses_shared_mask_email() -> None:
    """scripts/product_metrics_report.py must import mask_email from privacy_utils."""
    text_content = (REPO_ROOT / "scripts" / "product_metrics_report.py").read_text(encoding="utf-8")
    assert "from privacy_utils import" in text_content, (
        "scripts/product_metrics_report.py must import from shared privacy_utils"
    )
    assert "mask_email" in text_content


# ─── AC #7: ip_denied audit log payload ──────────────────────────────────────


@pytest.mark.asyncio
async def test_ac7_ip_denied_audit_log_payload_privacy_safe(
    sqlite_session_factory_builder, tmp_path,
) -> None:
    """The audit row written when IP is denied carries masked email, last segment, and expected mask only."""
    import auth.bearer as bearer
    from auth.bearer import _base_auth_details, TOKEN_EVENT_AUTH_FAILED_IP_DENIED  # may need expose
    from storage_models import Account, ServiceBearerToken, TokenUsageLog
    from sqlalchemy import select

    session_factory = await sqlite_session_factory_builder(tmp_path / "ipd.db")
    async with session_factory() as session:
        account = Account(email="leaky@example.com", password_hash="x", status="active")
        session.add(account)
        await session.commit()
        token = ServiceBearerToken(
            account_id=1, name="t", token_prefix="sbt_ipd",
            token_hash="h" * 64, status="active",
            allowed_ip_mask="10.0.0.0",
        )
        session.add(token)
        await session.commit()

    # Hit the helper directly to avoid wiring the full request stack.
    from auth_audit import add_token_usage_log
    async with session_factory() as session:
        async with session.begin():
            stmt = select(ServiceBearerToken).where(ServiceBearerToken.name == "t")
            tok = (await session.execute(stmt)).scalar_one()
            account = (await session.execute(select(Account).where(Account.id == 1))).scalar_one()
            add_token_usage_log(
                session,
                bearer_token_id=tok.id,
                event_type=TOKEN_EVENT_AUTH_FAILED_IP_DENIED,
                details=bearer.build_ip_denied_audit_details(account, tok, client_ip="203.0.113.42"),
            )

    async with session_factory() as session:
        rows = (await session.execute(
            select(TokenUsageLog).where(TokenUsageLog.event_type == TOKEN_EVENT_AUTH_FAILED_IP_DENIED)
        )).scalars().all()
    assert len(rows) == 1
    payload = json.loads(rows[0].details_json)
    # Privacy: no full email, no full client IP
    assert "leaky@example.com" not in rows[0].details_json
    assert "203.0.113.42" not in rows[0].details_json
    # Required keys
    assert payload.get("account_email_masked") == "le***@ex***.com"
    assert payload.get("client_ip_last_segment") == "42"
    assert payload.get("expected_mask") == "10.0.0.0"


# ─── AC #8: wildcard create emits structured warning ────────────────────────


@pytest.mark.asyncio
async def test_ac8_wildcard_create_emits_structured_warning(
    sqlite_session_factory_builder, tmp_path, caplog,
) -> None:
    from service_token_service import issue_service_bearer_token
    from storage_models import Account
    import logging

    session_factory = await sqlite_session_factory_builder(tmp_path / "wc.db")
    async with session_factory() as session:
        session.add(Account(email="wc@example.com", password_hash="x", status="active"))
        await session.commit()

    with caplog.at_level(logging.WARNING):
        async with session_factory() as session:
            await issue_service_bearer_token(
                session,
                account_id=1,
                name="wildcard-token",
                expires_in_days=30,
                ip_mask="*.*.*.*",
            )

    relevant = [r for r in caplog.records if "token_created_with_wildcard_ip" in (r.message or "")]
    assert relevant, "AC #8: wildcard create must emit RUNTIME_LOGGER.warning"
    rec = relevant[0]
    assert getattr(rec, "account_id", None) == 1
    assert getattr(rec, "token_id", None) is not None


@pytest.mark.asyncio
async def test_ac8_specific_ip_mask_does_not_emit_wildcard_warning(
    sqlite_session_factory_builder, tmp_path, caplog,
) -> None:
    from service_token_service import issue_service_bearer_token
    from storage_models import Account
    import logging

    session_factory = await sqlite_session_factory_builder(tmp_path / "sp.db")
    async with session_factory() as session:
        session.add(Account(email="sp@example.com", password_hash="x", status="active"))
        await session.commit()

    with caplog.at_level(logging.WARNING):
        async with session_factory() as session:
            await issue_service_bearer_token(
                session,
                account_id=1,
                name="specific-token",
                expires_in_days=30,
                ip_mask="1.2.3.4",
            )

    relevant = [r for r in caplog.records if "token_created_with_wildcard_ip" in (r.message or "")]
    assert relevant == [], "AC #8: specific mask must NOT emit wildcard warning"


# ─── AC #9: operator runbook exists ──────────────────────────────────────────


def test_ac9_operator_runbook_exists_and_lacks_secrets() -> None:
    runbook = REPO_ROOT / "artifacts" / "runbook-operator-ip-mask.md"
    assert runbook.exists(), "AC #9: operator runbook must be created"
    text = runbook.read_text(encoding="utf-8")
    # Must mention key SQL recipes
    assert "allowed_ip_mask" in text
    assert "service_bearer_tokens" in text
    assert "token_auth_failed_ip_denied" in text
    # Must NOT mention secrets
    assert "FEEDBACK_FINGERPRINT_PEPPER" not in text
    assert "STORAGE_ENCRYPTION_KEY" not in text
