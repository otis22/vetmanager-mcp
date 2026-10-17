"""Stage 408: required intent and provenance-safe rating upsert."""

import asyncio
import os

import pytest
from sqlalchemy import select

import storage
from prompts import get_report_ai_prompt_helper_text
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account, ReportAiJobRating
from report_ai_rating_service import rate_job, record_created_job
from tools.report_ai import REPORT_AI_RATING_GUIDANCE


@pytest.fixture
async def rating_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'rating408.db'}")
    storage.reset_storage_state()
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with storage.get_session_factory()() as session:
        session.add(Account(email="stage408@example.test"))
        await session.commit()
    yield
    storage.reset_storage_state()


async def _row(job_id: int) -> ReportAiJobRating:
    async with storage.get_session_factory()() as session:
        return await session.scalar(select(ReportAiJobRating).where(ReportAiJobRating.job_id == job_id))


@pytest.mark.asyncio
async def test_rating_schema_requires_intent_and_score():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    tool = tools["rate_report_ai_job"]
    assert set(tool.inputSchema["required"]) == {"job_id", "score", "intent_text"}
    assert "comment" in tool.inputSchema["properties"]
    assert "comment необязателен" in tool.description
    assert "intent_text" in tool.description and "score обязательны" in tool.description
    assert "same intent_text" in tools["create_report_ai_job"].description
    assert "rate_report_ai_job(job_id, score, intent_text)" in get_report_ai_prompt_helper_text()
    assert "intent_text and score are required; comment is optional" in REPORT_AI_RATING_GUIDANCE


@pytest.mark.asyncio
async def test_rating_without_placeholder_inserts_sanitized_intent(rating_db):
    result = await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=408,
                            score=2, intent_text="Клиент Иванов Иван +7 999 123-45-67: приёмы",
                            comment="pet@example.test не помог")
    row = await _row(408)
    assert result["score"] == row.score == 2
    assert row.intent_from_create is False
    assert "Иванов" not in row.intent_text and "999" not in row.intent_text
    assert "pet@example.test" not in (row.comment or "")
    assert row.rated_at is not None


@pytest.mark.asyncio
async def test_rating_keeps_original_intent_on_conflict(rating_db):
    await record_created_job(account_id=1, connection_id=10, domain="clinic-a",
                             job_id=409, intent_text="Исходный промпт")
    await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=409,
                   score=4, intent_text="Агентский дубль", comment="частично")
    row = await _row(409)
    assert row.intent_text == "Исходный промпт"
    assert row.intent_from_create is True
    assert row.score == 4 and row.comment == "частично"
    await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=409,
                   score=7, intent_text="Другой дубль")
    row = await _row(409)
    assert row.intent_text == "Исходный промпт" and row.score == 7 and row.comment is None


@pytest.mark.asyncio
async def test_late_original_create_replaces_only_rating_sourced_intent(rating_db):
    await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=410,
                   score=3, intent_text="Агентский промпт", comment="частично")
    assert await record_created_job(account_id=1, connection_id=10, domain="clinic-a",
                                    job_id=410, intent_text="Исходный промпт")
    row = await _row(410)
    assert row.intent_text == "Исходный промпт" and row.intent_from_create is True
    assert row.score == 3 and row.comment == "частично"


@pytest.mark.asyncio
async def test_deduplicated_create_does_not_claim_original_intent(rating_db):
    await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=411,
                   score=3, intent_text="Промпт из оценки")
    assert await record_created_job(account_id=1, connection_id=10, domain="clinic-a",
                                    job_id=411, intent_text="Новый текст дедупа", allow_new=False)
    row = await _row(411)
    assert row.intent_text == "Промпт из оценки" and row.intent_from_create is False


@pytest.mark.asyncio
async def test_concurrent_ratings_share_one_row_and_owner_key(rating_db):
    await asyncio.gather(
        rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=413,
                 score=3, intent_text="Первый промпт"),
        rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=413,
                 score=4, intent_text="Второй промпт"),
    )
    await rate_job(account_id=1, connection_id=11, domain="clinic-a", job_id=413,
                   score=5, intent_text="Другое подключение")
    await rate_job(account_id=1, connection_id=10, domain="clinic-b", job_id=413,
                   score=6, intent_text="Другой домен")
    async with storage.get_session_factory()() as session:
        rows = (await session.execute(select(ReportAiJobRating).where(
            ReportAiJobRating.job_id == 413))).scalars().all()
    assert len(rows) == 3
    original_key = next(row for row in rows if row.connection_id == 10 and row.domain == "clinic-a")
    assert original_key.score in (3, 4)


@pytest.mark.asyncio
@pytest.mark.parametrize("intent", ["", "   ", "a" * 20001])
async def test_rating_rejects_invalid_intent_before_storage(rating_db, intent):
    with pytest.raises(Exception):
        await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=412,
                       score=4, intent_text=intent)
    assert await _row(412) is None
