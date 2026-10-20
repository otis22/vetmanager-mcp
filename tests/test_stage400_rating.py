"""Stage 400: a report job can be rated without exposing its intent."""

from datetime import datetime, timedelta, timezone
import asyncio
import os
from pathlib import Path
import stat
import subprocess
from types import SimpleNamespace

import pytest
import httpx
import respx
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, select, update
from unittest.mock import AsyncMock

import service_metrics
import storage
from prompts import get_report_ai_prompt_helper_text
from server import mcp
from storage import Base, create_database_engine
from storage_models import Account
import tools.report_ai as report_ai
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock
from tool_access_registry import SCOPE_REPORT_AI_WRITE, TOOL_REQUIRED_SCOPES


@pytest.mark.asyncio
async def test_rating_is_visible_before_a_report_succeeds():
    advertised = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    descriptions = {name: tool.description for name, tool in advertised.items()}
    rating = descriptions["rate_report_ai_job"]
    rating_schema = advertised["rate_report_ai_job"].inputSchema
    assert "comment" in rating_schema["properties"]
    assert "comment" not in rating_schema.get("required", [])
    assert set(rating_schema["required"]) == {"job_id", "score", "intent_text"}
    for fragment in (
        "1 = отчёт даже не построился",
        "2 и выше — отчёт построился",
        "2 = построился, но задачу почти не решил",
        "5–6 = решил частично",
        "10 = задача решена полностью, ничего не пришлось добывать другими путями",
        "что именно не устроило в отчёте",
    ):
        assert fragment in rating
    assert "rate_report_ai_job" in descriptions["create_report_ai_job"]
    assert "rate_report_ai_job" in get_report_ai_prompt_helper_text()
    assert TOOL_REQUIRED_SCOPES["rate_report_ai_job"] == (SCOPE_REPORT_AI_WRITE,)


def test_any_agent_allowed_to_create_report_ai_job_can_rate_it():
    create_scopes = set(TOOL_REQUIRED_SCOPES["create_report_ai_job"])
    rating_scopes = set(TOOL_REQUIRED_SCOPES["rate_report_ai_job"])
    assert create_scopes
    assert rating_scopes
    assert rating_scopes <= create_scopes


@pytest.mark.parametrize("status, action", [
    ("ready_to_save", "save_report_ai_job_as_report"),
    ("needs_confirmation", "reject_report_ai_job_candidate"),
])
def test_numeric_string_job_id_keeps_next_action(status, action):
    job = {"id": "400", "status": status}
    report_ai._annotate_report_ai_next_action(job)
    calls = [job["next_action"]["call"]] if "call" in job["next_action"] else job["next_action"]["calls"]
    assert any(item["tool"] == action and item["arguments"]["job_id"] == 400 for item in calls)


@pytest.mark.asyncio
async def test_rating_persists_sanitized_prompt_and_replaces_score(tmp_path, monkeypatch):
    from report_ai_rating_service import record_created_job, rate_job
    from storage_models import ReportAiJobRating

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'ratings.db'}")
    storage.reset_storage_state()
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with storage.get_session_factory()() as session:
        session.add_all([Account(email="a@example.test"), Account(email="b@example.test")])
        await session.commit()

    prompt = "Клиент: Иванов Иван, +7 999 123-45-67, ivan@example.test — приёмы"
    await record_created_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400, intent_text=prompt)
    with pytest.raises(Exception):
        await rate_job(account_id=0, connection_id=10, domain="clinic-a", job_id=400, score=1,
                       intent_text=prompt)
    with pytest.raises(Exception):
        await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400, score=True,
                       intent_text=prompt)
    with pytest.raises(Exception):
        await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400, score=11,
                       intent_text=prompt)
    result = await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400, score=1,
                            intent_text=prompt,
                            comment="Клиент: Петров Пётр; pet@example.test")
    assert result["score"] == 1
    await record_created_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400,
                             intent_text="Другой промпт")
    await record_created_job(account_id=1, connection_id=10, domain="clinic-b", job_id=400,
                             intent_text="Отчёт второй клиники")
    await record_created_job(account_id=1, connection_id=11, domain="clinic-a", job_id=400,
                             intent_text="После переподключения")
    assert not await record_created_job(
        account_id=1, connection_id=10, domain="clinic-a", job_id=999,
        intent_text="Нельзя приписывать исходный промпт старому job", allow_new=False)
    assert await record_created_job(
        account_id=1, connection_id=10, domain="clinic-a", job_id=400,
        intent_text="Другой текст дедуплицированного запроса", allow_new=False)
    await asyncio.gather(
        record_created_job(account_id=1, connection_id=10, domain="clinic-a",
                           job_id=403, intent_text="Первый конкурентный вызов"),
        record_created_job(account_id=1, connection_id=10, domain="clinic-a",
                           job_id=403, intent_text="Второй конкурентный вызов"),
    )
    result = await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=400, score=7,
                            intent_text="Агентский дубль")
    assert result["score"] == 7
    async with storage.get_session_factory()() as session:
        rows = (await session.execute(select(ReportAiJobRating))).scalars().all()
        assert len(rows) == 4
        assert sum(row.job_id == 403 for row in rows) == 1
        row = next(row for row in rows if row.domain == "clinic-a" and row.connection_id == 10)
        assert row.job_id == 400 and row.score == 7
        assert row.created_at is not None and row.rated_at is not None
        assert "Иванов" not in row.intent_text
        assert "999" not in row.intent_text
        assert "ivan@example.test" not in row.intent_text
        assert "Другой промпт" not in row.intent_text
    storage.reset_storage_state()


@pytest.mark.asyncio
async def test_old_prompt_is_purged_after_rerating_even_without_account_activity(tmp_path, monkeypatch):
    from report_ai_rating_service import purge_expired_jobs, rate_job, record_created_job
    from storage_models import ReportAiJobRating

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'retention.db'}")
    storage.reset_storage_state()
    engine = create_database_engine(os.environ["DATABASE_URL"])
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    await engine.dispose()
    async with storage.get_session_factory()() as session:
        session.add(Account(email="idle@example.test"))
        await session.commit()
    await record_created_job(account_id=1, connection_id=10, domain="clinic-a", job_id=401,
                             intent_text="Сколько приёмов")
    old = datetime.now(timezone.utc) - timedelta(days=181)
    async with storage.get_session_factory()() as session:
        await session.execute(update(ReportAiJobRating).values(created_at=old))
        await session.commit()
    await rate_job(account_id=1, connection_id=10, domain="clinic-a", job_id=401, score=5,
                   intent_text="Сколько приёмов")
    assert await purge_expired_jobs(now=datetime.now(timezone.utc)) == 1
    async with storage.get_session_factory()() as session:
        assert (await session.execute(select(ReportAiJobRating))).scalars().all() == []
    storage.reset_storage_state()


def test_rating_metric_has_bounded_score_distribution():
    service_metrics.reset_service_metrics()
    service_metrics.record_report_ai_rating(score=1)
    service_metrics.record_report_ai_rating(score=10)
    metrics = service_metrics.render_prometheus_metrics()
    assert 'vetmanager_report_ai_ratings_total{score="1"} 1' in metrics
    assert 'vetmanager_report_ai_ratings_total{score="10"} 1' in metrics


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("raw_job_id", [400, "400"])
async def test_create_records_original_intent_before_wait_and_failed_job_has_guidance(monkeypatch, raw_job_id):
    billing_mock()
    register = AsyncMock(return_value=True)
    monkeypatch.setattr(report_ai, "record_created_job", register, raising=False)
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json={"success": True, "data": {
            "job": {"id": raw_job_id, "status": "failed"}}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await mcp.call_tool("create_report_ai_job", {"intent_text": "Отчёт по месяцам"})
    assert post.call_count == 1
    assert register.await_count == 1
    assert register.await_args.kwargs["intent_text"] == "Отчёт по месяцам"
    assert register.await_args.kwargs["job_id"] == 400
    assert "rate_report_ai_job" in str(result.structured_content)


@pytest.mark.asyncio
@respx.mock
async def test_create_keeps_job_id_when_rating_db_stalls(monkeypatch):
    billing_mock()
    async def blocked_registration(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(report_ai, "record_created_job", blocked_registration, raising=False)
    post = respx.post(f"{BASE}/rest/api/report-ai-job").mock(
        return_value=httpx.Response(201, json={"success": True, "data": {
            "job": {"id": 401, "status": "queued"}}}))
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        result = await asyncio.wait_for(
            mcp.call_tool("create_report_ai_job", {"intent_text": "Приёмы по месяцам"}),
            timeout=5,
        )
    assert post.call_count == 1
    assert result.structured_content["data"]["job"]["id"] == 401
    assert "mcp_rating_unavailable" in str(result.structured_content)
    assert "You can still rate it" in str(result.structured_content)


@pytest.mark.asyncio
@pytest.mark.parametrize("arguments", [
    {"job_id": 400, "score": True},
    {"job_id": True, "score": 5},
])
async def test_rating_rejects_boolean_input_at_mcp_boundary(monkeypatch, arguments):
    arguments["intent_text"] = "Сколько приёмов"
    writer = AsyncMock(return_value={"ok": True, "job_id": 400, "score": 1})
    monkeypatch.setattr(report_ai, "rate_job", writer)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        with pytest.raises(Exception):
            await mcp.call_tool("rate_report_ai_job", arguments)
    writer.assert_not_awaited()


def test_postgres_backup_is_private(tmp_path):
    project = Path(__file__).resolve().parents[1]
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(mode=0o755)
    backup_dir.chmod(0o755)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/bin/sh\nif [ \"$1\" = compose ]; then echo fake-container; else printf dump; fi\n")
    docker.chmod(0o755)
    env = {**os.environ, "BACKUP_DIR": str(backup_dir), "REMOTE_DIR": str(project),
           "PATH": str(fake_bin) + os.pathsep + os.environ["PATH"]}
    result = subprocess.run(["bash", str(project / "scripts/backup_postgres.sh")],
                            env=env, capture_output=True, text=True, check=False,
                            preexec_fn=lambda: os.umask(0o022))
    assert result.returncode == 0, result.stderr
    archive = next(backup_dir.glob("vetmanager-*.sql.gz"))
    assert stat.S_IMODE(backup_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(archive.stat().st_mode) == 0o600
    assert "umask 077" in (project / "scripts/backup_daily_cron.sh").read_text()


def test_rating_migration_has_retention_index_and_rollback(tmp_path, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migrate.db'}")
    command.upgrade(config, "20261017_000031")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    inspector = inspect(engine)
    assert "report_ai_job_ratings" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("report_ai_job_ratings")}
    assert {"account_id", "connection_id", "domain", "job_id", "intent_text", "intent_from_create",
            "score", "comment", "created_at", "rated_at"} <= columns
    indexes = {index["name"] for index in inspector.get_indexes("report_ai_job_ratings")}
    assert "ix_report_ai_job_ratings_created_at" in indexes
    engine.dispose()
    command.downgrade(config, "20261014_000029")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert "report_ai_job_ratings" not in inspect(engine).get_table_names()
    engine.dispose()


def test_predeploy_rollback_dump_omits_rating_rows(tmp_path, monkeypatch):
    from scripts import stage385_deploy

    calls = []
    monkeypatch.setattr(stage385_deploy, "_container", lambda *_args: "synthetic-pg")

    def fake_run(args, *, stdout, stderr, timeout):
        calls.append(args)
        stdout.write(b"PGDMP" + b"x" * 100)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(stage385_deploy.subprocess, "run", fake_run)
    stage385_deploy._backup_pg("synthetic-project", tmp_path)
    assert "--exclude-table-data=public.report_ai_job_ratings" in calls[0][-1]
