"""Stage 374: first-session contract, durable observations and completed cohort."""

import asyncio
import os
from pathlib import Path
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import httpx
import respx
from alembic import command
from fastmcp import FastMCP
from fastmcp import Client
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker

import activation_telemetry
import first_session
import service_metrics
from service_token_service import issue_service_bearer_token
import service_token_service
import oauth_service
from storage import Base, create_database_engine
from storage_models import Account, AccountFirstSession, OAuthClient, OAuthGrant, VetmanagerConnection
from oauth_service import create_oauth_authorization_code, exchange_oauth_authorization_code, exchange_oauth_refresh_token, _pkce_s256_challenge
from tests.runtime_factories import make_runtime_credentials
from tests.test_migrations import _make_alembic_config
from tool_error_tracking import ToolErrorTrackingMiddleware
from runtime_auth import use_runtime_credentials
import tools.report_ai as report_ai
from tests.test_stage170_report_ai_tools import BASE, bearer_runtime_patch, billing_mock


def test_postgres_race_guard_runs_in_ci():
    workflow = Path(".github/workflows/test.yml").read_text()
    postgres_job = workflow.split("  postgres-activation-telemetry:", 1)[1]
    assert "tests/test_stage374_first_session.py" in postgres_job


@pytest.mark.asyncio
async def test_instructions_keep_first_journey_and_privacy():
    from server import mcp
    async with Client(mcp) as client:
        text = client.initialize_result.instructions
    for phrase in ("doctors works today", "person's expectation", "clinic's real data",
                   "preview", "approve saving", "not verified real data", "report_problem",
                   "Do not paste raw tool response bodies"):
        assert phrase in text
    assert "welcome_first_session" not in text


@pytest.mark.asyncio
async def test_fastmcp_middleware_sees_semantic_error_contract():
    seen = []

    class Probe(Middleware):
        async def on_call_tool(self, context, call_next):
            try:
                result = await call_next(context)
            except ToolError:
                seen.append("raised")
                raise
            seen.append(result.is_error)
            return result

    app = FastMCP("probe")
    app.add_middleware(Probe())

    @app.tool
    async def empty_read() -> dict:
        return {"data": []}

    @app.tool
    async def fails() -> dict:
        raise ToolError("failure")

    async with Client(app) as client:
        assert client.initialize_result is not None
        assert await client.list_tools()
    assert seen == [], "initialize and tools/list are outside the data-tool middleware"
    await app.call_tool("empty_read", {})
    with pytest.raises(ToolError):
        await app.call_tool("fails", {})
    assert seen == [False, "raised"]


@pytest.mark.asyncio
async def test_tool_middleware_only_marks_successful_data_tool(monkeypatch):
    marks = []

    async def observe(account_id, field):
        marks.append((account_id, field))

    monkeypatch.setattr("tool_error_tracking.observe_first_action", observe)
    middleware = ToolErrorTrackingMiddleware()
    credentials = make_runtime_credentials("example", "secret", account_id=374)

    async def invoke(name, result=None, error=None):
        async def next_call(_context):
            if error:
                raise error
            return result

        with use_runtime_credentials(credentials):
            return await middleware.on_call_tool(SimpleNamespace(message=SimpleNamespace(name=name)), next_call)

    await invoke("get_clients", SimpleNamespace(is_error=False, structured_content={"data": []}))
    credentials.source = "oauth"
    await invoke("get_clients", SimpleNamespace(is_error=False, structured_content={"data": []}))
    await invoke("get_clients", SimpleNamespace(is_error=True))
    await invoke("get_clients", SimpleNamespace(is_error=False, structured_content={"success": False}))
    await invoke("report_problem", SimpleNamespace(is_error=False))
    await invoke("get_report_ai_prompt_helper", SimpleNamespace(is_error=False))
    with pytest.raises(ToolError):
        await invoke("get_clients", error=ToolError("denied"))
    assert marks == [(374, "first_tool_success_at"), (374, "first_tool_success_at")]


def test_migration_upgrade_downgrade_without_backfill(tmp_path):
    config = _make_alembic_config(tmp_path)
    command.upgrade(config, "20261002_000026")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    with engine.begin() as conn:
        conn.exec_driver_sql("INSERT INTO accounts (email, status) VALUES ('old@example.test', 'active')")
    command.upgrade(config, "head")
    assert "account_first_sessions" in inspect(engine).get_table_names()
    columns = {column["name"]: column for column in inspect(engine).get_columns("account_first_sessions")}
    assert columns["first_token_issued_at"]["nullable"] is False
    assert columns["first_tool_success_at"]["nullable"] is True
    assert columns["first_report_saved_at"]["nullable"] is True
    assert any(fk["options"].get("ondelete") == "CASCADE" for fk in inspect(engine).get_foreign_keys("account_first_sessions"))
    with engine.connect() as conn:
        assert conn.exec_driver_sql("SELECT count(*) FROM account_first_sessions").scalar_one() == 0
    command.downgrade(config, "20261002_000026")
    assert "account_first_sessions" not in inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.asyncio
async def test_bearer_anchor_is_first_only_and_observations_survive_restart(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "first-session.db")
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "2026-01-01T00:00:00Z")
    monkeypatch.setattr(first_session, "get_session_factory", lambda: factory)
    async with factory() as session:
        account = Account(email="first@example.test", created_at=datetime.now(timezone.utc))
        session.add(account)
        await session.commit()
        account_id = account.id
    async with factory() as session:
        await issue_service_bearer_token(session, account_id=account_id, name="first", ip_mask="*.*.*.*")
    async with factory() as session:
        anchor = await session.get(AccountFirstSession, account_id)
        assert anchor is not None
        assert anchor.first_tool_success_at is None
        issued = anchor.first_token_issued_at
    async with factory() as session:
        await issue_service_bearer_token(session, account_id=account_id, name="second", ip_mask="*.*.*.*")
    await first_session.observe_first_action(account_id, "first_tool_success_at")
    async with factory() as session:
        anchor = await session.get(AccountFirstSession, account_id)
        tool_at = anchor.first_tool_success_at
        assert anchor.first_token_issued_at == issued and tool_at is not None
    await first_session.observe_first_action(account_id, "first_tool_success_at")
    await first_session.observe_first_action(account_id, "first_report_saved_at")
    async with factory() as session:
        anchor = await session.get(AccountFirstSession, account_id)
        report_at = anchor.first_report_saved_at
        assert anchor.first_tool_success_at == tool_at and report_at is not None
    await first_session.observe_first_action(account_id, "first_report_saved_at")
    async with factory() as session:
        anchor = await session.get(AccountFirstSession, account_id)
        assert anchor.first_report_saved_at == report_at


@pytest.mark.asyncio
async def test_oauth_code_anchors_once_and_refresh_cannot_substitute_missing_anchor(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "oauth-first.db")
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "2026-01-01T00:00:00Z")
    verifier = "v" * 43
    client_id = "vm_oc_stage374"
    resource = "https://example.test/mcp"
    redirect = "https://example.test/callback"
    async with factory() as session:
        account = Account(email="oauth-first@example.test", created_at=datetime.now(timezone.utc))
        session.add(account)
        await session.flush()
        connection = VetmanagerConnection(account_id=account.id, auth_mode="domain_api_key", status="active", domain="example")
        session.add(connection)
        session.add(OAuthClient(
            client_id=client_id, client_name="Test", redirect_uris_json='["https://example.test/callback"]',
            token_endpoint_auth_method="none", grant_types_json='["authorization_code","refresh_token"]',
            response_types_json='["code"]', scope="clients.read", status="active",
        ))
        await session.commit()
        account_id, connection_id = account.id, connection.id
    async with factory() as session:
        code = await create_oauth_authorization_code(session, {
            "client_id": client_id, "redirect_uri": redirect, "resource": resource,
            "scope": "clients.read", "code_challenge": _pkce_s256_challenge(verifier),
            "code_challenge_method": "S256", "access_preset": "read_only",
        }, account_id=account_id, vetmanager_connection_id=connection_id)
    async with factory() as session:
        pair = await exchange_oauth_authorization_code(session, {
            "code": code, "client_id": client_id, "redirect_uri": redirect,
            "resource": resource, "code_verifier": verifier,
        })
    async with factory() as session:
        anchor = await session.get(AccountFirstSession, account_id)
        assert anchor is not None and anchor.first_tool_success_at is None
        issued = anchor.first_token_issued_at
    async with factory() as session:
        rotated = await exchange_oauth_refresh_token(session, {
            "refresh_token": pair["refresh_token"], "client_id": client_id, "resource": resource,
        })
        assert rotated["access_token"]
    async with factory() as session:
        assert (await session.get(AccountFirstSession, account_id)).first_token_issued_at == issued
        await session.delete(await session.get(AccountFirstSession, account_id))
        await session.commit()
    async with factory() as session:
        await exchange_oauth_refresh_token(session, {
            "refresh_token": rotated["refresh_token"], "client_id": client_id, "resource": resource,
        })
        assert await session.get(AccountFirstSession, account_id) is None


@pytest.mark.asyncio
async def test_failed_telemetry_insert_keeps_credential_and_prevents_later_false_anchor(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "failed-anchor.db")
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "2026-01-01T00:00:00Z")
    async with factory() as session:
        account = Account(email="failed-anchor@example.test", created_at=datetime.now(timezone.utc))
        session.add(account)
        await session.commit()
        account_id = account.id
    bind = factory.kw["bind"].sync_engine
    failed = False

    def fail_once(_conn, _cursor, statement, _parameters, _context, _executemany):
        nonlocal failed
        if not failed and "INSERT INTO account_first_sessions" in statement:
            failed = True
            raise RuntimeError("telemetry insert failed")

    event.listen(bind, "before_cursor_execute", fail_once)
    try:
        async with factory() as session:
            await issue_service_bearer_token(session, account_id=account_id, name="first", ip_mask="*.*.*.*")
    finally:
        event.remove(bind, "before_cursor_execute", fail_once)
    assert failed
    async with factory() as session:
        assert await session.get(AccountFirstSession, account_id) is None
        await issue_service_bearer_token(session, account_id=account_id, name="later", ip_mask="*.*.*.*")
    async with factory() as session:
        assert await session.get(AccountFirstSession, account_id) is None


@pytest.mark.asyncio
async def test_invalid_rollout_cutoff_disables_telemetry_without_blocking_credential(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "invalid-cutoff.db")
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "invalid")
    first_session._LAST_FAILURE_LOG.clear()
    original_warning = first_session.RUNTIME_LOGGER.warning

    def broken_telemetry_logger(message, *args, **kwargs):
        if message == "First-session telemetry failed":
            raise RuntimeError("logger failed")
        return original_warning(message, *args, **kwargs)

    monkeypatch.setattr(first_session.RUNTIME_LOGGER, "warning", broken_telemetry_logger)
    async with factory() as session:
        account = Account(email="invalid-cutoff@example.test", created_at=datetime.now(timezone.utc))
        session.add(account)
        await session.commit()
        account_id = account.id
    async with factory() as session:
        token, raw = await issue_service_bearer_token(session, account_id=account_id, name="still issued", ip_mask="*.*.*.*")
        assert token.id and raw
        assert await session.get(AccountFirstSession, account_id) is None


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_cross_worker_issuance_waits_for_failed_first_insert(monkeypatch):
    database_url = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
    assert database_url.startswith("postgresql") and database_url.endswith("/vetmanager_test")
    engine = create_database_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "2026-01-01T00:00:00Z")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as session:
            account = Account(email="stage374-race@example.test", created_at=datetime.now(timezone.utc))
            session.add(account)
            await session.commit()
            account_id = account.id
        failed = False

        def fail_once(_conn, _cursor, statement, _parameters, _context, _executemany):
            nonlocal failed
            if not failed and "INSERT INTO account_first_sessions" in statement:
                failed = True
                raise RuntimeError("telemetry insert failed")

        event.listen(engine.sync_engine, "before_cursor_execute", fail_once)
        original = service_token_service.lock_account_and_check_first_credential
        first_locked = asyncio.Event()
        release_first = asyncio.Event()
        calls = 0
        hold_on = 1

        async def held_lock(session, selected_account_id):
            nonlocal calls
            result = await original(session, selected_account_id)
            calls += 1
            if calls == hold_on:
                first_locked.set()
                await release_first.wait()
            return result

        monkeypatch.setattr(service_token_service, "lock_account_and_check_first_credential", held_lock)

        async def issue(name):
            async with factory() as session:
                await issue_service_bearer_token(session, account_id=account_id, name=name, ip_mask="*.*.*.*")

        first = asyncio.create_task(issue("first"))
        await asyncio.wait_for(first_locked.wait(), timeout=5)
        second = asyncio.create_task(issue("second"))
        await asyncio.sleep(0.15)
        acquired_before_release = calls
        release_first.set()
        await asyncio.gather(first, second)
        assert acquired_before_release == 1, "second issuer must wait on the Account row lock"
        event.remove(engine.sync_engine, "before_cursor_execute", fail_once)
        assert failed and calls == 2
        async with factory() as session:
            assert await session.get(AccountFirstSession, account_id) is None
            assert len((await session.execute(select(service_token_service.ServiceBearerToken))).scalars().all()) == 2
            other = Account(email="stage374-race-normal@example.test", created_at=datetime.now(timezone.utc))
            session.add(other)
            await session.commit()
            other_id = other.id
        account_id = other_id
        await asyncio.gather(issue("parallel-a"), issue("parallel-b"))
        async with factory() as session:
            assert await session.get(AccountFirstSession, other_id) is not None
            assert len((await session.execute(
                select(service_token_service.ServiceBearerToken).where(
                    service_token_service.ServiceBearerToken.account_id == other_id
                )
            )).scalars().all()) == 2
        monkeypatch.setattr(first_session, "get_session_factory", lambda: factory)
        await asyncio.gather(*(
            first_session.observe_first_action(other_id, "first_tool_success_at")
            for _ in range(3)
        ))
        async with factory() as session:
            first_success = (await session.get(AccountFirstSession, other_id)).first_tool_success_at
            assert first_success is not None
        await first_session.observe_first_action(other_id, "first_tool_success_at")
        async with factory() as session:
            assert (await session.get(AccountFirstSession, other_id)).first_tool_success_at == first_success

        # The same account lock must serialize a bearer issuer against OAuth.
        async with factory() as session:
            mixed = Account(email="stage374-race-mixed@example.test", created_at=datetime.now(timezone.utc))
            session.add(mixed)
            await session.flush()
            connection = VetmanagerConnection(account_id=mixed.id, auth_mode="domain_api_key", status="active", domain="example")
            session.add(connection)
            session.add(OAuthClient(
                client_id="vm_oc_stage374_race", client_name="Test", redirect_uris_json='["https://example.test/callback"]',
                token_endpoint_auth_method="none", grant_types_json='["authorization_code"]',
                response_types_json='["code"]', scope="clients.read", status="active",
            ))
            await session.commit()
            mixed_id, connection_id = mixed.id, connection.id
        verifier = "v" * 43
        async with factory() as session:
            code = await create_oauth_authorization_code(session, {
                "client_id": "vm_oc_stage374_race", "redirect_uri": "https://example.test/callback",
                "resource": "https://example.test/mcp", "scope": "clients.read",
                "code_challenge": _pkce_s256_challenge(verifier), "code_challenge_method": "S256",
                "access_preset": "read_only",
            }, account_id=mixed_id, vetmanager_connection_id=connection_id)
        monkeypatch.setattr(oauth_service, "lock_account_and_check_first_credential", held_lock)
        account_id = mixed_id
        failed = False
        event.listen(engine.sync_engine, "before_cursor_execute", fail_once)
        first_locked.clear()
        release_first.clear()
        hold_on = calls + 1
        first = asyncio.create_task(issue("mixed-bearer"))
        await asyncio.wait_for(first_locked.wait(), timeout=5)

        async def exchange():
            async with factory() as session:
                await exchange_oauth_authorization_code(session, {
                    "code": code, "client_id": "vm_oc_stage374_race",
                    "redirect_uri": "https://example.test/callback", "resource": "https://example.test/mcp",
                    "code_verifier": verifier,
                })

        second = asyncio.create_task(exchange())
        await asyncio.sleep(0.15)
        acquired_before_release = calls
        release_first.set()
        await asyncio.gather(first, second)
        event.remove(engine.sync_engine, "before_cursor_execute", fail_once)
        assert acquired_before_release == hold_on and failed
        async with factory() as session:
            assert await session.get(AccountFirstSession, mixed_id) is None
            assert (await session.scalar(select(OAuthGrant).where(OAuthGrant.account_id == mixed_id))) is not None
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("payload,expected", [
    ({"success": True, "data": {"report_id": 374}}, 1),
    ({"success": True, "data": {"job": {"id": 374, "status": "saved"}}}, 0),
    ({"success": True, "data": {"job": {"id": 374, "status": "ready_to_save"}}}, 0),
])
async def test_save_marks_only_positive_report_id(monkeypatch, payload, expected):
    billing_mock()
    respx.post(f"{BASE}/rest/api/report-ai-job/374/save").mock(
        return_value=httpx.Response(200, json=payload)
    )
    marked = AsyncMock()
    monkeypatch.setattr(report_ai, "observe_first_action", marked)
    headers, runtime = bearer_runtime_patch()
    with headers, runtime:
        await __import__("server").mcp.call_tool("save_report_ai_job_as_report", {
            "job_id": 374, "title": "MCP test report October 2026",
        })
    assert marked.await_count == expected
    if expected:
        assert marked.await_args.args == (1, "first_report_saved_at")


@pytest.mark.asyncio
async def test_completed_cohort_boundaries_and_scan_failure_keep_last_snapshot(
    tmp_path, sqlite_session_factory_builder, monkeypatch,
):
    factory = await sqlite_session_factory_builder(tmp_path / "cohort.db")
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", "2026-01-01T00:00:00Z")
    now = datetime(2026, 3, 1, tzinfo=timezone.utc)
    async with factory() as session:
        for index, days in enumerate((30, 29, 7, 6, 31), start=1):
            issued = now - timedelta(days=days)
            account = Account(email=f"cohort{index}@example.test", created_at=issued - timedelta(hours=1))
            session.add(account)
            await session.flush()
            session.add(AccountFirstSession(
                account_id=account.id, first_token_issued_at=issued,
                first_tool_success_at=issued + timedelta(days=7) if index == 2 else issued + timedelta(hours=1),
                first_report_saved_at=issued + timedelta(days=7) if index == 2 else issued + timedelta(hours=2),
            ))
        await session.commit()
    async with factory() as session:
        values = await activation_telemetry.scan_first_session_cohort(session, now=now)
    assert values == {
        "eligible_accounts": 2,
        "report_saved_7d_accounts": 1,
        "tool_success_7d_accounts": 1,
        "tool_time_median_seconds": 3600.0,
    }
    service_metrics.set_first_session_gauges(values)
    lines = service_metrics.render_prometheus_metrics()
    assert "vetmanager_first_session_eligible_accounts 2" in lines
    assert "vetmanager_first_session_report_saved_7d_accounts 1" in lines
    assert "vetmanager_first_session_tool_time_median_seconds 3600.0" in lines
    assert "vetmanager_first_session_eligible_accounts{" not in lines
    activation_telemetry.reset_activation_telemetry_state()
    service_metrics.reset_service_metrics()
    async with factory() as session:
        await activation_telemetry.scan_activation_telemetry(session, now=now)
        assert service_metrics.snapshot_service_metrics()["first_session_gauges"] == values
        service_metrics.reset_service_metrics()
        await activation_telemetry.scan_activation_telemetry(session, now=now + timedelta(seconds=30))
        assert service_metrics.snapshot_service_metrics()["first_session_gauges"] == values
    activation_telemetry.reset_activation_telemetry_state()
    service_metrics.reset_service_metrics()
    async with factory() as session:
        await activation_telemetry.scan_activation_telemetry(session, now=now)
    assert service_metrics.snapshot_service_metrics()["first_session_gauges"] == values
    async def broken_sql(session, *, now):
        await session.execute(text("SELECT * FROM missing_first_session_table"))

    monkeypatch.setattr(activation_telemetry, "scan_first_session_cohort", broken_sql)
    activation_telemetry.reset_activation_telemetry_state()
    async with factory() as session:
        rollback = AsyncMock(wraps=session.rollback)
        monkeypatch.setattr(session, "rollback", rollback)
        await activation_telemetry.scan_activation_telemetry(session, now=now)
        assert rollback.await_count >= 1
    assert service_metrics.snapshot_service_metrics()["first_session_gauges"] == values
