"""Stage 376: expiry notice contract and atomic claim guards."""

import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from fastmcp.tools.tool import ToolResult
from mcp.types import TextContent
from sqlalchemy import select

from storage_models import Account, ServiceBearerToken, TokenUsageStat


def test_expiry_notice_migration_upgrade_downgrade(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'migrate.db'}")
    command.upgrade(config, "head")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert "expiry_notice_at" in {item["name"] for item in inspect(engine).get_columns("token_usage_stats")}
    engine.dispose()
    command.downgrade(config, "-1")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert "expiry_notice_at" not in {item["name"] for item in inspect(engine).get_columns("token_usage_stats")}
    engine.dispose()


def test_installed_toolresult_preserves_structured_wire_content():
    original = TextContent(type="text", text="original")
    warning = TextContent(type="text", text="warning")
    result = ToolResult(content=[original, warning], structured_content={"success": True, "data": []})
    content, structured = result.to_mcp_result()
    assert [block.text for block in content] == ["original", "warning"]
    assert structured == {"success": True, "data": []}


def test_notice_text_is_private_and_declines():
    from token_expiry_notice import expiry_notice_text

    for days, suffix in [(1, "день"), (2, "дня"), (7, "дней"), (14, "дней")]:
        message = expiry_notice_text(days)
        assert f"через {days} {suffix}" in message
        for phrase in ("новый токен", "теми же правами", "очистки данных", "IP-ограничением", "замените"):
            assert phrase in message
        assert "vm_st_" not in message and "https://" not in message and "token_id" not in message


def test_expiry_timezone_normalization():
    from token_expiry_notice import _utc

    assert _utc(datetime(2026, 10, 10, 12)) == datetime(2026, 10, 10, 12, tzinfo=timezone.utc)
    assert _utc(datetime(2026, 10, 10, 15, tzinfo=timezone(timedelta(hours=3)))) == datetime(
        2026, 10, 10, 12, tzinfo=timezone.utc,
    )


@pytest.mark.asyncio
async def test_middleware_appends_only_to_success_and_resets_handoff(monkeypatch):
    from types import SimpleNamespace
    import token_expiry_notice
    from tool_error_tracking import ToolErrorTrackingMiddleware

    calls = []

    async def claim(account_id, bearer_token_id, *, prepare):
        calls.append((account_id, bearer_token_id))
        return prepare(1)

    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", claim)
    middleware = ToolErrorTrackingMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="get_clients"))

    async def success(_):
        token_expiry_notice.set_notice_subject(12, 34)
        return ToolResult(content=[TextContent(type="text", text="[]")], structured_content={"success": True, "data": []})

    result = await middleware.on_call_tool(context, success)
    assert [block.text for block in result.content] == ["[]", token_expiry_notice.expiry_notice_text(1)]
    assert result.structured_content == {"success": True, "data": []}
    assert token_expiry_notice.get_notice_subject() is None

    async def no_subject(_):
        return ToolResult(content=[TextContent(type="text", text="plain")])

    assert [block.text for block in (await middleware.on_call_tool(context, no_subject)).content] == ["plain"]
    assert calls == [(12, 34)]

    async def failed(_):
        token_expiry_notice.set_notice_subject(12, 34)
        return ToolResult(content=[TextContent(type="text", text="failed")], structured_content={"success": False})

    assert [block.text for block in (await middleware.on_call_tool(context, failed)).content] == ["failed"]
    assert calls == [(12, 34)]

    async def flagged_error(_):
        token_expiry_notice.set_notice_subject(12, 34)
        return ToolResult(content=[TextContent(type="text", text="error")], is_error=True)

    assert (await middleware.on_call_tool(context, flagged_error)).is_error
    assert calls == [(12, 34)]

    async def validation_error(_):
        token_expiry_notice.set_notice_subject(12, 34)
        raise ValueError("validation")

    with pytest.raises(ValueError):
        await middleware.on_call_tool(context, validation_error)
    assert token_expiry_notice.get_notice_subject() is None
    assert calls == [(12, 34)]


@pytest.mark.asyncio
async def test_claim_rolling_window_and_token_isolation(tmp_path, sqlite_session_factory_builder):
    from token_expiry_notice import claim_expiry_notice

    factory = await sqlite_session_factory_builder(tmp_path / "expiry.db")
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    async with factory() as session:
        account = Account(email="expiry@example.test", status="active")
        session.add(account)
        await session.flush()
        tokens = []
        for number in range(2):
            token = ServiceBearerToken(account_id=account.id, name=f"token-{number}")
            token.set_raw_token(f"vm_st_test_{number}")
            token.expires_at = now + timedelta(days=7)
            session.add(token)
            tokens.append(token)
        await session.commit()
        account_id, ids = account.id, [token.id for token in tokens]

    assert await claim_expiry_notice(account_id, ids[0], now=now, session_factory=factory) == 7
    assert await claim_expiry_notice(account_id, ids[0], now=now + timedelta(hours=23), session_factory=factory) is None
    assert await claim_expiry_notice(account_id, ids[1], now=now, session_factory=factory) == 7
    assert await claim_expiry_notice(account_id, ids[0], now=now + timedelta(hours=24), session_factory=factory) == 6
    async with factory() as session:
        stat = await session.scalar(select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == ids[0]))
        assert stat.expiry_notice_at is not None


@pytest.mark.asyncio
async def test_claim_concurrent_sessions_one_winner(tmp_path, sqlite_session_factory_builder):
    from token_expiry_notice import claim_expiry_notice

    factory = await sqlite_session_factory_builder(tmp_path / "expiry-race.db")
    now = datetime.now(timezone.utc)
    async with factory() as session:
        account = Account(email="race@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="race")
        token.set_raw_token("vm_st_test_race")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id
    results = await asyncio.gather(
        claim_expiry_notice(account_id, token_id, now=now, session_factory=factory),
        claim_expiry_notice(account_id, token_id, now=now, session_factory=factory),
    )
    assert sum(value is not None for value in results) == 1
    # A new engine models a worker restart: the claim lives in the database.
    second_factory = await sqlite_session_factory_builder(tmp_path / "expiry-race.db")
    assert await claim_expiry_notice(account_id, token_id, now=now, session_factory=second_factory) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("remaining,expected", [
    (15, None), (14, 14), (8, 8), (7, 7), (2, 2), (1, 1), (0, None), (None, None),
])
async def test_claim_deadline_boundaries(tmp_path, sqlite_session_factory_builder, remaining, expected):
    from token_expiry_notice import claim_expiry_notice

    factory = await sqlite_session_factory_builder(tmp_path / "boundary.db")
    now = datetime(2026, 10, 10, tzinfo=timezone.utc)
    async with factory() as session:
        account = Account(email="boundary@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="boundary")
        token.set_raw_token("vm_st_test_boundary")
        token.expires_at = now.replace(tzinfo=None) + timedelta(days=remaining) if remaining is not None else None
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id
    assert await claim_expiry_notice(account_id, token_id, now=now, session_factory=factory) == expected


@pytest.mark.asyncio
async def test_claim_ignores_disabled_or_wrong_account(tmp_path, sqlite_session_factory_builder):
    from token_expiry_notice import claim_expiry_notice

    factory = await sqlite_session_factory_builder(tmp_path / "inactive.db")
    now = datetime.now(timezone.utc)
    async with factory() as session:
        account = Account(email="inactive@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="inactive", status="disabled")
        token.set_raw_token("vm_st_test_inactive")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id
    assert await claim_expiry_notice(account_id, token_id, now=now, session_factory=factory) is None
    async with factory() as session:
        token = await session.get(ServiceBearerToken, token_id)
        token.status = "active"
        await session.commit()
    assert await claim_expiry_notice(account_id + 1, token_id, now=now, session_factory=factory) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["disabled", "expired"])
async def test_claim_rechecks_token_at_update(tmp_path, sqlite_session_factory_builder, change):
    from sqlalchemy import Update, update
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from token_expiry_notice import claim_expiry_notice

    ordinary = await sqlite_session_factory_builder(tmp_path / f"recheck-{change}.db")
    now = datetime.now(timezone.utc)
    async with ordinary() as session:
        account = Account(email="recheck@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="recheck")
        token.set_raw_token("vm_st_test_recheck")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id

    class ChangingSession(AsyncSession):
        async def execute(self, statement, *args, **kwargs):
            if isinstance(statement, Update) and statement.table.name == "token_usage_stats":
                values = {"status": "disabled"} if change == "disabled" else {"expires_at": now - timedelta(seconds=1)}
                await super().execute(update(ServiceBearerToken).where(ServiceBearerToken.id == token_id).values(**values))
            return await super().execute(statement, *args, **kwargs)

    changing = async_sessionmaker(ordinary.kw["bind"], class_=ChangingSession, expire_on_commit=False)
    assert await claim_expiry_notice(account_id, token_id, now=now, session_factory=changing) is None


@pytest.mark.asyncio
async def test_wrapper_handoff_bearer_and_oauth(monkeypatch):
    from types import SimpleNamespace
    import tools
    from token_expiry_notice import get_notice_subject, open_notice_subject, reset_notice_subject

    credentials = SimpleNamespace(account_id=3, bearer_token_id=9, source="bearer", is_depersonalized=False)

    async def resolve():
        return credentials

    async def original():
        return {"success": True}

    monkeypatch.setattr(tools, "resolve_runtime_credentials", resolve)
    monkeypatch.setattr(tools, "_ensure_tool_scopes_allowed", lambda *_: None)
    wrapped = tools._wrap_tool_with_depersonalization(original, tool_name="get_clients")
    slot = open_notice_subject()
    try:
        assert await wrapped() == {"success": True}
        assert get_notice_subject() == (3, 9)
        credentials.source = "oauth"
        assert await wrapped() == {"success": True}
        assert get_notice_subject() is None
    finally:
        reset_notice_subject(slot)


@pytest.mark.asyncio
async def test_middleware_database_or_annotation_failure_keeps_result(monkeypatch):
    from types import SimpleNamespace
    import token_expiry_notice
    from tool_error_tracking import ToolErrorTrackingMiddleware

    context = SimpleNamespace(message=SimpleNamespace(name="get_clients"))
    original = ToolResult(content=[TextContent(type="text", text="original")], structured_content={"success": True})

    async def call(_):
        token_expiry_notice.set_notice_subject(3, 9)
        return original

    async def broken_db(*args, **kwargs):
        raise RuntimeError("simulated")

    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", broken_db)
    assert await ToolErrorTrackingMiddleware().on_call_tool(context, call) is original

    monkeypatch.setattr("tool_error_tracking.RUNTIME_LOGGER.warning", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("logger")))
    assert await ToolErrorTrackingMiddleware().on_call_tool(context, call) is original

    async def broken_annotation(*args, prepare, **kwargs):
        return prepare(1)

    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", broken_annotation)
    monkeypatch.setattr(token_expiry_notice, "expiry_notice_text", lambda _: (_ for _ in ()).throw(ValueError("simulated")))
    assert await ToolErrorTrackingMiddleware().on_call_tool(context, call) is original


@pytest.mark.asyncio
async def test_empty_success_gets_notice(monkeypatch):
    from types import SimpleNamespace
    import token_expiry_notice
    from tool_error_tracking import ToolErrorTrackingMiddleware

    async def claim(*args, prepare, **kwargs):
        return prepare(2)

    async def call(_):
        token_expiry_notice.set_notice_subject(3, 9)
        return ToolResult(content=[])

    monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", claim)
    result = await ToolErrorTrackingMiddleware().on_call_tool(
        SimpleNamespace(message=SimpleNamespace(name="get_clients")), call,
    )
    assert [block.text for block in result.content] == [token_expiry_notice.expiry_notice_text(2)]



@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["acquire", "select", "update", "commit"])
async def test_optional_claim_deadline_covers_each_stage(tmp_path, sqlite_session_factory_builder, stage):
    from time import monotonic
    from sqlalchemy import Update
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from token_expiry_notice import claim_expiry_notice

    ordinary = await sqlite_session_factory_builder(tmp_path / f"slow-{stage}.db")
    now = datetime.now(timezone.utc)
    async with ordinary() as session:
        account = Account(email="slow@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="slow")
        token.set_raw_token("vm_st_test_slow")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id

    class SlowTransaction:
        def __init__(self, transaction):
            self.transaction = transaction

        async def __aenter__(self):
            return await self.transaction.__aenter__()

        async def __aexit__(self, *args):
            if stage == "commit" and args[0] is None:
                await asyncio.sleep(0.65)
            return await self.transaction.__aexit__(*args)

    class SlowSession(AsyncSession):
        def begin(self):
            return SlowTransaction(super().begin())

        async def scalar(self, statement, *args, **kwargs):
            if stage == "select":
                await asyncio.sleep(0.65)
            return await super().scalar(statement, *args, **kwargs)

        async def execute(self, statement, *args, **kwargs):
            if stage == "update" and isinstance(statement, Update):
                await asyncio.sleep(0.65)
            return await super().execute(statement, *args, **kwargs)

    slow_factory = async_sessionmaker(ordinary.kw["bind"], class_=SlowSession, expire_on_commit=False)

    if stage == "acquire":
        class SlowAcquire:
            async def __aenter__(self):
                await asyncio.sleep(0.65)
                self.session = slow_factory()
                return await self.session.__aenter__()

            async def __aexit__(self, *args):
                return await self.session.__aexit__(*args)

        claim_factory = SlowAcquire
    else:
        claim_factory = slow_factory
    started = monotonic()
    with pytest.raises(TimeoutError):
        await claim_expiry_notice(account_id, token_id, now=now, session_factory=claim_factory)
    assert monotonic() - started < 0.6
    async with ordinary() as session:
        stat = await session.scalar(select(TokenUsageStat).where(TokenUsageStat.bearer_token_id == token_id))
        assert stat is None or stat.expiry_notice_at is None


@pytest.mark.asyncio
async def test_external_cancellation_propagates_and_releases_connection(tmp_path, sqlite_session_factory_builder):
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from token_expiry_notice import claim_expiry_notice

    ordinary = await sqlite_session_factory_builder(tmp_path / "cancel.db")
    now = datetime.now(timezone.utc)
    async with ordinary() as session:
        account = Account(email="cancel@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="cancel")
        token.set_raw_token("vm_st_test_cancel")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id

    entered = asyncio.Event()

    class HeldSession(AsyncSession):
        async def scalar(self, statement, *args, **kwargs):
            await self.connection()
            entered.set()
            await asyncio.sleep(10)
            return await super().scalar(statement, *args, **kwargs)

    held = async_sessionmaker(ordinary.kw["bind"], class_=HeldSession, expire_on_commit=False)
    task = asyncio.create_task(claim_expiry_notice(account_id, token_id, now=now, session_factory=held))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with ordinary() as session:
        assert await session.get(ServiceBearerToken, token_id) is not None


@pytest.mark.asyncio
async def test_pool_checkout_wait_is_inside_deadline(tmp_path, sqlite_session_factory_builder):
    from time import monotonic
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from token_expiry_notice import claim_expiry_notice

    path = tmp_path / "pool.db"
    ordinary = await sqlite_session_factory_builder(path)
    now = datetime.now(timezone.utc)
    async with ordinary() as session:
        account = Account(email="pool@example.test", status="active")
        session.add(account)
        await session.flush()
        token = ServiceBearerToken(account_id=account.id, name="pool")
        token.set_raw_token("vm_st_test_pool")
        token.expires_at = now + timedelta(days=1)
        session.add(token)
        await session.commit()
        account_id, token_id = account.id, token.id

    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", pool_size=1, max_overflow=0, pool_timeout=5)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.connect():
            started = monotonic()
            with pytest.raises(TimeoutError):
                await claim_expiry_notice(account_id, token_id, now=now, session_factory=factory)
            assert monotonic() - started < 0.6
        assert await claim_expiry_notice(account_id, token_id, now=now, session_factory=factory) == 1
    finally:
        await engine.dispose()
