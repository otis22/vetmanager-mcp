"""Stage 227 regression: PostgreSQL must execute the activation aggregate."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker

import activation_telemetry
from service_metrics import snapshot_service_metrics
from storage import Base, create_database_engine
from storage_models import Account, ActivationEvent, ServiceBearerToken, VetmanagerConnection


NOW = datetime(2026, 8, 21, 12, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_activation_scan_sets_event_and_age_gauges_and_caches() -> None:
    """Regression for PostgreSQL rejecting separately-built coalesce expressions."""
    database_url = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
    assert database_url.startswith("postgresql"), "stage 227 requires an explicit test-only PostgreSQL URL"
    assert make_url(database_url).database == "vetmanager_test", "stage 227 only permits vetmanager_test"
    activation_telemetry.reset_activation_telemetry_state()
    engine = create_database_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        async with session_factory() as session:
            account = Account(email="stage227@example.invalid", status="active", created_at=NOW, updated_at=NOW)
            session.add(account)
            await session.flush()
            session.add(VetmanagerConnection(
                account_id=account.id,
                auth_mode="domain_api_key",
                status="active",
                domain="stage227",
                created_at=NOW,
                updated_at=NOW,
            ))
            session.add(ServiceBearerToken(
                account_id=account.id,
                name="stage227",
                token_prefix="sbt_stage227",
                token_hash="stage227_" + "x" * 48,
                status="active",
                allowed_ip_mask="*.*.*.*",
                created_at=NOW - timedelta(days=1),
                last_used_at=NOW - timedelta(hours=2),
            ))
            session.add_all([
                ActivationEvent(
                    account_id=account.id,
                    event_name="integration_saved",
                    auth_mode="domain_api_key",
                    device_class="desktop",
                    reason_class=None,
                    created_at=NOW,
                ),
                ActivationEvent(
                    account_id=account.id,
                    event_name="integration_failed",
                    auth_mode="domain_api_key",
                    device_class="mobile",
                    reason_class="auth_error",
                    created_at=NOW,
                ),
            ])
            await session.commit()

            await activation_telemetry.scan_activation_telemetry(session, now=NOW)
            first_snapshot = snapshot_service_metrics()
            assert first_snapshot["activation_event_accounts"] == {
                "integration_failed|mobile|domain_api_key|auth_error": 1,
                "integration_saved|desktop|domain_api_key|none": 1,
            }
            assert first_snapshot["account_last_request_age_hours"] == {str(account.id): 2.0}

            session.add(ActivationEvent(
                account_id=account.id,
                event_name="token_copied",
                auth_mode="unknown",
                device_class="desktop",
                created_at=NOW,
            ))
            await session.commit()
            await activation_telemetry.scan_activation_telemetry(session, now=NOW + timedelta(seconds=30))
            assert snapshot_service_metrics()["activation_event_accounts"] == first_snapshot["activation_event_accounts"]
    finally:
        activation_telemetry.reset_activation_telemetry_state()
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
