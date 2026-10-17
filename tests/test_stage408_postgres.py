"""Opt-in PostgreSQL proof for the production rating upsert dialect."""

import os

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import select

import storage
from report_ai_rating_service import rate_job, record_created_job
from storage_models import Account, ReportAiJobRating


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("STAGE408_PG_URL"), reason="isolated PostgreSQL URL required")
async def test_postgres_rating_upsert_and_late_original(monkeypatch):
    url = os.environ["STAGE408_PG_URL"]
    monkeypatch.setenv("DATABASE_URL", url)
    storage.reset_storage_state()
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", url)
    command.upgrade(config, "head")
    async with storage.get_session_factory()() as session:
        account = Account(email="stage408-postgres@example.test")
        session.add(account)
        await session.commit()
        await session.refresh(account)
        account_id = account.id
    try:
        await rate_job(account_id=account_id, connection_id=408, domain="clinic-a",
                       job_id=408, score=3, intent_text="Промпт из оценки")
        await record_created_job(account_id=account_id, connection_id=408,
                                 domain="clinic-a", job_id=408,
                                 intent_text="Исходный промпт")
        await rate_job(account_id=account_id, connection_id=408, domain="clinic-a",
                       job_id=408, score=7, intent_text="Агентский дубль")
        async with storage.get_session_factory()() as session:
            rows = (await session.execute(select(ReportAiJobRating).where(
                ReportAiJobRating.account_id == account_id))).scalars().all()
            assert len(rows) == 1
            assert rows[0].intent_text == "Исходный промпт"
            assert rows[0].intent_from_create is True and rows[0].score == 7
    finally:
        storage.reset_storage_state()
