"""Opt-in .env Vetmanager API + isolated PostgreSQL bearer rating proof."""

import json
import os
import re
import secrets
from contextlib import contextmanager
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

import storage
from storage_models import Account, ReportAiJobRating
from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


@pytest.fixture
def prepared_web_db(monkeypatch):
    url = os.environ.get("STAGE400_PG_URL")
    if not url:
        pytest.skip("isolated stage 400 PostgreSQL URL absent")
    monkeypatch.setenv("DATABASE_URL", url)
    monkeypatch.setenv("WEB_SESSION_SECRET", secrets.token_urlsafe(32))
    monkeypatch.setenv("WEB_SESSION_SECURE", "0")
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", Fernet.generate_key().decode())
    storage.reset_storage_state()
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    command.upgrade(config, "head")
    yield "stage400-isolated-postgres"
    storage.reset_storage_state()


def _rpc(response: httpx.Response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: "))
    return response.json()


def _issue_bearer(client: httpx.Client, label: str) -> tuple[str, int]:
    email = f"stage400-{label}-{uuid4().hex}@example.test"
    response = _post_with_csrf_sync(client, "/register", data={
        "email": email, "password": secrets.token_urlsafe(24)})
    assert response.status_code == 200
    response = _post_with_csrf_sync(client, "/account/integration", data={
        "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
        "api_key": os.environ["TEST_API_KEY"],
    }, page_path="/account")
    assert response.status_code == 200
    response = _post_with_csrf_sync(client, "/account/tokens", data={
        "token_name": "Stage 400 rating proof", "expires_in_days": "1",
        "ip_mask": "*.*.*.*", "access_preset": "full_access",
        "confirm_full_access": "1",
    }, page_path="/account")
    assert response.status_code == 200
    token = re.search(r"vm_st_[A-Za-z0-9_-]+", response.text)
    assert token is not None
    engine = create_engine(storage.normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
    with Session(engine) as session:
        account_id = session.scalar(select(Account.id).where(Account.email == email))
    engine.dispose()
    assert account_id is not None
    return token.group(0), account_id


@contextmanager
def _mcp_client(base_url: str, token: str):
    with httpx.Client(base_url=base_url, timeout=90, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }) as client:
        response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage400-live", "version": "1"},
            },
        })
        assert response.status_code == 200
        client.headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized"}).status_code in (200, 202)
        yield client


def _call(client: httpx.Client, name: str, arguments: dict, request_id: int) -> tuple[int, dict]:
    response = client.post("/mcp", json={
        "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    assert response.status_code == 200
    return response.status_code, _rpc(response)["result"]


@pytest.mark.skipif(not os.environ.get("STAGE400_PG_URL") or not os.environ.get("TEST_API_KEY"),
                    reason="isolated PostgreSQL and .env Vetmanager test contour required")
def test_stage400_live_create_rate_and_sql_shape(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        owner_token, owner_id = _issue_bearer(web, "owner")
    with _mcp_client(live_server_url, owner_token) as owner:
        code, created = _call(owner, "create_report_ai_job", {
            "intent_text": (
                "Количество приёмов по месяцам за последние три месяца, без персональных данных. "
                f"Метка проверки {uuid4().hex[:8]} не является фильтром данных."
            ),
            "wait_seconds": 30,
        }, 2)
        assert created.get("isError") is not True
        assert created["structuredContent"]["data"].get("is_deduplicated") is not True
        job = created["structuredContent"]["data"]["job"]
        job_id = job["id"]
        status = job.get("status")
        request_id = 3
        for _ in range(6):
            if status in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}:
                break
            if status == "needs_confirmation":
                code, rejected = _call(owner, "reject_report_ai_job_candidate", {"job_id": job_id}, request_id)
                assert rejected.get("isError") is not True
                request_id += 1
            code, polled = _call(owner, "get_report_ai_job", {
                "job_id": job_id, "wait_seconds": 30}, request_id)
            assert polled.get("isError") is not True
            status = polled["structuredContent"]["data"]["job"].get("status")
            request_id += 1
        assert status in {"ready_to_save", "saved", "existing_report_matched", "failed", "rejected"}
        score = 1 if status in {"failed", "rejected"} else 2
        rate_code, rated = _call(owner, "rate_report_ai_job", {
            "job_id": job_id, "score": score,
            "comment": "Проверка журнала; итоговые строки не использованы",
        }, request_id)
        assert rated.get("isError") is not True
        assert rated["structuredContent"]["score"] == score
        metrics = owner.get("/metrics")
        assert metrics.status_code == 200
        assert f'vetmanager_report_ai_ratings_total{{score="{score}"}}' in metrics.text
        assert 'vetmanager_report_ai_rating_purges_total{outcome="success"}' in metrics.text

    engine = create_engine(storage.normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
    with Session(engine) as session:
        row = session.scalar(select(ReportAiJobRating).where(
            ReportAiJobRating.account_id == owner_id,
            ReportAiJobRating.job_id == job_id))
        assert row is not None
        assert row.score == score and row.intent_text and row.created_at and row.rated_at
        safe_shape = {"columns": sorted(row.__table__.columns.keys()),
                      "owner_matches": row.account_id == owner_id,
                      "job_matches": row.job_id == job_id,
                      "score": row.score, "prompt_nonempty": bool(row.intent_text),
                      "timestamp_fields_present": bool(row.created_at and row.rated_at)}
    engine.dispose()

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as web:
        other_token, _ = _issue_bearer(web, "other")
    with _mcp_client(live_server_url, other_token) as other:
        denied_code, denied = _call(other, "rate_report_ai_job", {
            "job_id": job_id, "score": 10}, 2)
        assert denied.get("isError") is True
    print("STAGE400_LIVE", {"create_http": code, "rate_http": rate_code,
                            "other_http": denied_code, "other_denied": True,
                            "record": safe_shape})
