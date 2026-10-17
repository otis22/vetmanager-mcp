"""Stage 408: real Vetmanager jobs and live MCP rating calls on the .env contour."""

import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

import storage
from storage_models import ReportAiJobRating
from tests.test_stage400_live import _call, _issue_bearer, _mcp_client

pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env Vetmanager test contour required")
def test_live_rate_with_and_without_placeholder(live_server_url):
    import httpx

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        token, account_id = _issue_bearer(web, "408")

    created_intents = []
    with _mcp_client(live_server_url, token) as client:
        for index in (1, 2):
            subject = ("Количество приёмов по месяцам за последние три месяца" if index == 1
                       else "Количество счетов по месяцам за 1900 год")
            original = (f"{subject}. "
                        f"Метка проверки {uuid4().hex[:8]} не является фильтром данных.")
            code, created = _call(client, "create_report_ai_job", {"intent_text": original}, index + 1)
            assert code == 200 and created.get("isError") is not True
            assert created["structuredContent"]["data"].get("is_deduplicated") is not True
            job_id = created["structuredContent"]["data"]["job"]["id"]
            created_intents.append((job_id, original))

        engine = create_engine(storage.normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
        first_id, first_intent = created_intents[0]
        second_id, _ = created_intents[1]
        with Session(engine) as session:
            first = session.scalar(select(ReportAiJobRating).where(
                ReportAiJobRating.account_id == account_id,
                ReportAiJobRating.job_id == first_id))
            assert first is not None and first.intent_text == first_intent
            assert first.intent_from_create is True
            session.execute(delete(ReportAiJobRating).where(
                ReportAiJobRating.account_id == account_id,
                ReportAiJobRating.job_id == second_id))
            session.commit()

        first_code, first_rating = _call(client, "rate_report_ai_job", {
            "job_id": first_id, "score": 2, "intent_text": "Агентский дубль"}, 4)
        second_code, second_rating = _call(client, "rate_report_ai_job", {
            "job_id": second_id, "score": 3,
            "intent_text": "Клиент Иванов Иван +7 999 123-45-67: приёмы"}, 5)
        absent_intent_code, absent_intent = _call(client, "rate_report_ai_job", {
            "job_id": second_id, "score": 4}, 6)
        absent_score_code, absent_score = _call(client, "rate_report_ai_job", {
            "job_id": second_id, "intent_text": "Приёмы"}, 7)

        assert first_code == second_code == absent_intent_code == absent_score_code == 200
        assert first_rating.get("isError") is not True
        assert second_rating.get("isError") is not True
        assert absent_intent.get("isError") is True
        assert absent_score.get("isError") is True

        with Session(engine) as session:
            first = session.scalar(select(ReportAiJobRating).where(
                ReportAiJobRating.account_id == account_id,
                ReportAiJobRating.job_id == first_id))
            second = session.scalar(select(ReportAiJobRating).where(
                ReportAiJobRating.account_id == account_id,
                ReportAiJobRating.job_id == second_id))
            assert first.intent_text == first_intent and first.intent_from_create is True
            assert first.score == 2
            assert second is not None and second.intent_from_create is False
            assert second.score == 3 and second.intent_text
            assert "Иванов" not in second.intent_text and "999" not in second.intent_text
        engine.dispose()

    print("STAGE408_LIVE", {
        "create_http": 200, "placeholder_rate_http": first_code,
        "missing_placeholder_rate_http": second_code,
        "missing_intent_http": absent_intent_code,
        "missing_intent_is_error": absent_intent.get("isError"),
        "missing_score_http": absent_score_code,
        "missing_score_is_error": absent_score.get("isError"),
        "placeholder_rating": first_rating.get("structuredContent"),
        "inserted_rating": second_rating.get("structuredContent"),
        "existing_intent_preserved": True, "inserted_intent_sanitized": True,
    })
