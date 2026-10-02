"""Stage 359: journal work and fetched rows stay bounded by accounts."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import event, inspect, select, text

from activation_telemetry import (
    _accounts_with_requests, reset_activation_telemetry_state, scan_activation_telemetry,
)
from auth_audit import TOKEN_EVENT_AUTH_SUCCEEDED
from service_metrics import snapshot_service_metrics
from storage_models import Account, ServiceBearerToken, TokenUsageLog, VetmanagerConnection
from scripts.product_metrics_report import _journal_accounts_since


@pytest.mark.asyncio
async def test_accounts_with_requests_does_not_fetch_the_154k_event_journal(
    tmp_path: Path, sqlite_session_factory_builder, caplog,
):
    factory = await sqlite_session_factory_builder(tmp_path / "stage359.db")
    now = datetime(2026, 10, 2, tzinfo=timezone.utc)
    async with factory() as session:
        requested = Account(email="requested@example.invalid", status="active")
        noisy = Account(email="noisy@example.invalid", status="active")
        session.add_all([requested, noisy])
        await session.flush()
        token = ServiceBearerToken(
            account_id=noisy.id,
            name="noise", token_prefix="sbt_stage359", token_hash="x" * 64,
            status="active", allowed_ip_mask="*.*.*.*",
        )
        session.add(token)
        session.add(VetmanagerConnection(
            account_id=noisy.id, auth_mode="domain_api_key", status="active",
            domain="stage359-clinic", created_at=now, updated_at=now,
        ))
        await session.flush()
        # One SQL INSERT ... SELECT avoids 154k ORM objects and makes the old
        # Python-side de-dup visibly transfer far more rows than accounts.
        await session.execute(text("""
            WITH RECURSIVE seq(n) AS (
                SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 154086
            )
            INSERT INTO token_usage_logs (account_id, bearer_token_id, event_type, event_at)
            SELECT :account_id, :token_id, :event_type, :event_at FROM seq
        """), {"account_id": noisy.id, "token_id": token.id,
               "event_type": TOKEN_EVENT_AUTH_SUCCEEDED,
               "event_at": now.strftime("%Y-%m-%d %H:%M:%S.%f")})
        await session.commit()

        # This is exactly the old transfer shape: the table has production-scale
        # successful events but only two accounts.
        old_rows = (await session.execute(
            select(TokenUsageLog.account_id).where(
                TokenUsageLog.event_type == TOKEN_EVENT_AUTH_SUCCEEDED
            )
        )).scalars().all()
        assert len(old_rows) == 154086

        statements = []
        def capture(_conn, _cursor, statement, _params, _context, _executemany):
            if "token_usage_logs" in statement:
                statements.append(statement.lower())
        event.listen(session.bind.sync_engine, "before_cursor_execute", capture)
        try:
            result = await _accounts_with_requests(session, account_ids={requested.id}, since=now - timedelta(days=7))
            assert result == set()
            result = await _accounts_with_requests(session, account_ids={noisy.id}, since=now)
            assert result == {noisy.id}
            assert await _journal_accounts_since(session, now) == {noisy.id}
            assert statements and all("exists" in statement for statement in statements)
        finally:
            event.remove(session.bind.sync_engine, "before_cursor_execute", capture)

        # Same rows, legacy set/max semantics and the rewritten scan: one
        # first request, no activity inside 7d, and both silence thresholds.
        reset_activation_telemetry_state()
        emitted = await scan_activation_telemetry(session, now=now + timedelta(days=8))
        metrics = snapshot_service_metrics()
        assert metrics["activation_funnel_accounts"]["first_mcp_request"] == len(set(old_rows))
        assert metrics["activation_funnel_accounts"]["with_recent_usage_7d"] == 0
        assert metrics["account_last_request_age_hours"][str(noisy.id)] == 8 * 24
        assert emitted == 2
        silence = [r for r in caplog.records if getattr(r, "event_name", None) == "account_traffic_silent"]
        assert {r.threshold_hours for r in silence if r.account_id == noisy.id} == {24, 72}
        reset_activation_telemetry_state()


def test_journal_lookup_index_is_in_schema():
    names = {index.name for index in TokenUsageLog.__table__.indexes}
    assert "ix_token_usage_logs_account_event_at" in names


def test_index_migration_round_trip_on_schema_copy(tmp_path: Path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine

    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migration359.db'}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    name = "ix_token_usage_logs_account_event_at"
    assert name in {i["name"] for i in inspect(engine).get_indexes("token_usage_logs")}
    command.downgrade(config, "20260924_000025")
    assert name not in {i["name"] for i in inspect(engine).get_indexes("token_usage_logs")}
    command.upgrade(config, "head")
    assert name in {i["name"] for i in inspect(engine).get_indexes("token_usage_logs")}
    engine.dispose()
