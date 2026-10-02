"""Stage 359 PostgreSQL gate: migration and account probes on prod-sized journal."""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

from storage import normalize_database_url_for_migrations


@pytest.mark.postgres
def test_postgres_journal_index_upgrade_plan_and_downgrade(caplog):
    async_url = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
    assert async_url.startswith("postgresql+asyncpg://")
    url = make_url(async_url)
    assert url.database == "vetmanager_test"
    sync_url = normalize_database_url_for_migrations(async_url)
    schema = "stage359_" + uuid.uuid4().hex[:12]
    admin = sa.create_engine(sync_url)
    with admin.begin() as conn:
        conn.execute(sa.text(f"CREATE SCHEMA {schema}"))
    prior_options = os.environ.get("PGOPTIONS")
    os.environ["PGOPTIONS"] = f"-c search_path={schema}"
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "alembic"))
    config.set_main_option("sqlalchemy.url", sync_url)
    engine = sa.create_engine(sync_url)
    try:
        command.upgrade(config, "20260924_000025")
        with engine.begin() as conn:
            conn.execute(sa.text("""
                INSERT INTO accounts (email, status, created_at, updated_at)
                VALUES ('stage359-noisy@example.invalid', 'active', now(), now()),
                       ('stage359-quiet@example.invalid', 'active', now(), now())
            """))
            ids = conn.execute(sa.text("""
                SELECT id FROM accounts WHERE email LIKE 'stage359-%@example.invalid'
                ORDER BY id
            """)).scalars().all()
            conn.execute(sa.text("""
                INSERT INTO vetmanager_connections
                    (account_id, auth_mode, status, domain, created_at, updated_at)
                VALUES (:noisy, 'domain_api_key', 'active', 'stage359-noisy', now(), now()),
                       (:quiet, 'domain_api_key', 'active', 'stage359-quiet', now(), now())
            """), {"noisy": ids[0], "quiet": ids[1]})
            conn.execute(sa.text("""
                INSERT INTO service_bearer_tokens
                    (account_id, name, token_prefix, token_hash, status, allowed_ip_mask,
                     created_at)
                VALUES (:account, 'stage359', 'sbt_stage359_pg', :hash, 'active', '*.*.*.*', now())
            """), {"account": ids[0], "hash": "x" * 64})
            conn.execute(sa.text("""
                INSERT INTO service_bearer_tokens
                    (account_id, name, token_prefix, token_hash, status, allowed_ip_mask,
                     created_at)
                VALUES (:account, 'stage359-quiet', 'sbt_stage359_quiet', :hash,
                        'active', '*.*.*.*', now())
            """), {"account": ids[1], "hash": "y" * 64})
            token_id = conn.execute(sa.text("""
                SELECT id FROM service_bearer_tokens WHERE token_prefix = 'sbt_stage359_pg'
            """)).scalar_one()
            conn.execute(sa.text("""
                INSERT INTO token_usage_logs
                    (account_id, bearer_token_id, event_type, event_at)
                SELECT :account, :token, 'token_auth_succeeded', now() - interval '8 days'
                FROM generate_series(1, 154086)
            """), {"account": ids[0], "token": token_id})
        start = time.monotonic()
        command.upgrade(config, "head")
        build_seconds = time.monotonic() - start
        with engine.begin() as conn:
            conn.execute(sa.text("ANALYZE token_usage_logs"))
            valid = conn.execute(sa.text("""
                SELECT i.indisvalid FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid
                WHERE c.relname='ix_token_usage_logs_account_event_at'
            """)).scalar_one()
            assert valid is True
            # The first query mirrors the scan's bounded EXISTS for a quiet
            # account. The second mirrors the descending last-request lookup.
            probe_plan = "\n".join(conn.execute(sa.text("""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT a.id FROM accounts a WHERE a.id=:account AND EXISTS (
                    SELECT 1 FROM token_usage_logs l
                    WHERE l.account_id=a.id AND l.event_type='token_auth_succeeded'
                    AND l.event_at>=now()-interval '7 days')
            """), {"account": ids[1]}).scalars().all())
            latest_plan = "\n".join(conn.execute(sa.text("""
                EXPLAIN (ANALYZE, BUFFERS)
                SELECT l.event_at FROM token_usage_logs l
                WHERE l.account_id=:account AND l.event_type='token_auth_succeeded'
                ORDER BY l.event_at DESC LIMIT 1
            """), {"account": ids[1]}).scalars().all())
            assert "Index Scan" in probe_plan or "Index Only Scan" in probe_plan, probe_plan
            assert "Seq Scan on token_usage_logs" not in probe_plan, probe_plan
            assert "ix_token_usage_logs_account_event_at" in latest_plan, latest_plan
            assert "Seq Scan on token_usage_logs" not in probe_plan + latest_plan
            print(f"stage359 index build seconds={build_seconds:.3f}\n{probe_plan}\n{latest_plan}")
            if os.environ.get("STAGE359_PERFORMANCE_GATE") == "1":
                assert build_seconds < 30, build_seconds
        async def timed_scan():
            from sqlalchemy.ext.asyncio import async_sessionmaker
            from activation_telemetry import reset_activation_telemetry_state, scan_activation_telemetry
            from service_metrics import snapshot_service_metrics
            from storage import create_database_engine

            async_engine = create_database_engine(async_url)
            try:
                reset_activation_telemetry_state()
                factory = async_sessionmaker(async_engine, expire_on_commit=False)
                async with factory() as session:
                    await session.execute(sa.text(f"SET search_path TO {schema}"))
                    started = time.monotonic()
                    emitted = await scan_activation_telemetry(session)
                    elapsed = time.monotonic() - started
                    gauges = snapshot_service_metrics()["account_last_request_age_hours"]
                    assert {str(ids[0]), str(ids[1])}.issubset(gauges)
                    assert emitted == 2
                    return elapsed
            finally:
                reset_activation_telemetry_state()
                await async_engine.dispose()

        from observability_logging import RUNTIME_LOGGER

        RUNTIME_LOGGER.logger.addHandler(caplog.handler)
        try:
            scan_seconds = asyncio.run(timed_scan())
        finally:
            RUNTIME_LOGGER.logger.removeHandler(caplog.handler)
        print(f"stage359 full scan seconds={scan_seconds:.3f}")
        silence = {
            (record.account_id, record.threshold_hours)
            for record in caplog.records
            if getattr(record, "event_name", None) == "account_traffic_silent"
        }
        assert silence == {(ids[0], 24), (ids[0], 72)}
        if os.environ.get("STAGE359_PERFORMANCE_GATE") == "1":
            assert scan_seconds < 2, scan_seconds
        command.downgrade(config, "20260924_000025")
        assert "ix_token_usage_logs_account_event_at" not in {
            i["name"] for i in sa.inspect(engine).get_indexes("token_usage_logs")
        }
        # Simulate a process dying after CREATE INDEX CONCURRENTLY committed
        # but before Alembic advanced its revision marker.
        with engine.begin() as conn:
            conn.execute(sa.text("""
                CREATE INDEX ix_token_usage_logs_account_event_at
                ON token_usage_logs (account_id, event_type, event_at)
            """))
        command.upgrade(config, "head")
        # Simulate a process dying after DROP INDEX CONCURRENTLY committed
        # but before Alembic advanced the downgrade revision marker.
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            conn.execute(sa.text("DROP INDEX CONCURRENTLY ix_token_usage_logs_account_event_at"))
        command.downgrade(config, "20260924_000025")
        assert "ix_token_usage_logs_account_event_at" not in {
            i["name"] for i in sa.inspect(engine).get_indexes("token_usage_logs")
        }
    finally:
        engine.dispose()
        if prior_options is None:
            os.environ.pop("PGOPTIONS", None)
        else:
            os.environ["PGOPTIONS"] = prior_options
        with admin.begin() as conn:
            conn.execute(sa.text(f"DROP SCHEMA {schema} CASCADE"))
        admin.dispose()
