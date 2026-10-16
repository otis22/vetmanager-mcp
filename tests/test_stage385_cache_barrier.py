"""A completed write must invalidate another slot's local GET cache."""

import asyncio
import hashlib
import os
from uuid import uuid4
import httpx
import pytest
import respx

import vetmanager_client
import cache_write_barrier
from exceptions import HostResolutionError, VetmanagerTimeoutError, VetmanagerUpstreamUnavailable
from request_cache import InMemoryTaggedCache
from sqlalchemy.ext.asyncio import async_sessionmaker
from storage import Base, create_database_engine
from tests.runtime_factories import make_client_with_resolved_runtime


def test_cache_barrier_migration_upgrade_downgrade(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    config = Config("alembic.ini")
    config.set_main_option("script_location", "alembic")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{tmp_path / 'barrier-migrate.db'}")
    command.upgrade(config, "20261014_000029")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert "vetmanager_cache_barriers" in inspect(engine).get_table_names()
    assert {"tag_hash", "generation", "active_writes"} == {
        column["name"] for column in inspect(engine).get_columns("vetmanager_cache_barriers")}
    engine.dispose()
    command.downgrade(config, "-1")
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    assert "vetmanager_cache_barriers" not in inspect(engine).get_table_names()
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.postgres
async def test_postgres_write_barrier_counts_overlapping_workers(monkeypatch):
    url = os.environ.get("POSTGRES_TEST_DATABASE_URL", "")
    assert url.startswith("postgresql") and url.endswith("/vetmanager_test")
    engine = create_database_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(cache_write_barrier, "get_session_factory", lambda: factory)
    tag = hashlib.sha256(uuid4().bytes).hexdigest()
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await asyncio.gather(cache_write_barrier.begin_write(tag),
                             cache_write_barrier.begin_write(tag))
        assert await cache_write_barrier.read_generation(tag) is None
        await cache_write_barrier.finish_write(tag)
        assert await cache_write_barrier.read_generation(tag) is None
        await cache_write_barrier.finish_write(tag)
        assert await cache_write_barrier.read_generation(tag) == 2
    finally:
        await engine.dispose()


@pytest.fixture
def barrier_db(prepared_web_db):
    # prepared_web_db may dispose a previous async engine with asyncio.run(),
    # which clears pytest-asyncio's current loop before the first test here.
    created_loop = None
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        created_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(created_loop)
    try:
        yield prepared_web_db
    finally:
        if created_loop is not None:
            asyncio.set_event_loop(None)
            created_loop.close()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("reader_account_id", [1, 2])
async def test_write_on_slot_b_prevents_old_get_on_slot_a(
        monkeypatch, barrier_db, reader_account_id):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    value = {"version": 1}

    def response(request):
        if request.method == "POST":
            value["version"] = 2
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"data": {"version": value["version"]}})

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={
            "data": {"url": "https://clinic-a.vetmanager.cloud"}}))
    route = respx.route(url="https://clinic-a.vetmanager.cloud/rest/api/client",
                        method__in=["GET", "POST"]).mock(side_effect=response)
    slot_a = InMemoryTaggedCache()
    slot_b = InMemoryTaggedCache()
    reader = make_client_with_resolved_runtime("clinic-a", "test-key")
    reader._account_id = reader_account_id
    writer = make_client_with_resolved_runtime("clinic-a", "test-key")
    monkeypatch.setattr(vetmanager_client, "REQUEST_CACHE", slot_a)
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 1
    monkeypatch.setattr(vetmanager_client, "REQUEST_CACHE", slot_b)
    await writer.post("/rest/api/client", json={"name": "safe-test"})
    monkeypatch.setattr(vetmanager_client, "REQUEST_CACHE", slot_a)
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 2
    assert route.call_count == 3


@pytest.mark.asyncio
@respx.mock
async def test_pg_barrier_failure_stops_upstream_write(monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    async def unavailable(_tag):
        raise OSError("database unavailable")
    monkeypatch.setattr(cache_write_barrier, "begin_write", unavailable)
    route = respx.post("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"success": True}))
    client = make_client_with_resolved_runtime("clinic-a", "test-key")
    with pytest.raises(VetmanagerUpstreamUnavailable) as error:
        await client.post("/rest/api/client", json={"name": "safe-test"})
    assert error.value.status_code == 503
    assert route.call_count == 0


@pytest.mark.asyncio
async def test_unknown_upstream_write_outcome_keeps_pg_fence(monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    client = make_client_with_resolved_runtime("clinic-a", "test-key")

    async def uncertain(*_args, **_kwargs):
        client._write_dispatch_started = True
        raise VetmanagerTimeoutError("Response lost after the write may have started")

    monkeypatch.setattr(client, "_request_core", uncertain)
    with pytest.raises(VetmanagerTimeoutError):
        await client.post("/rest/api/client", json={"name": "safe-test"})
    tag = cache_write_barrier.tag_hash(domain="clinic-a", entity="client")
    assert await cache_write_barrier.read_generation(tag) is None


@pytest.mark.asyncio
async def test_known_pre_dispatch_failure_releases_pg_fence(monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    client = make_client_with_resolved_runtime("clinic-a", "test-key")

    async def no_host(*_args, **_kwargs):
        raise HostResolutionError("No clinic host is available")

    monkeypatch.setattr(client, "_request_core", no_host)
    with pytest.raises(HostResolutionError):
        await client.post("/rest/api/client", json={"name": "safe-test"})
    tag = cache_write_barrier.tag_hash(domain="clinic-a", entity="client")
    assert await cache_write_barrier.read_generation(tag) == 1


@pytest.mark.asyncio
@respx.mock
async def test_failed_finish_keeps_durable_fence_and_bypasses_old_cache(
        monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    value = {"version": 1}

    def response(request):
        if request.method == "POST":
            value["version"] = 2
            return httpx.Response(200, json={"success": True})
        return httpx.Response(200, json={"data": {"version": value["version"]}})

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={
            "data": {"url": "https://clinic-a.vetmanager.cloud"}}))
    route = respx.route(url="https://clinic-a.vetmanager.cloud/rest/api/client",
                        method__in=["GET", "POST"]).mock(side_effect=response)
    reader = make_client_with_resolved_runtime("clinic-a", "test-key")
    writer = make_client_with_resolved_runtime("clinic-a", "test-key")
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 1
    async def failed_finish(_tag):
        raise OSError("database unavailable after upstream write")
    monkeypatch.setattr(cache_write_barrier, "finish_write", failed_finish)
    await writer.post("/rest/api/client", json={"name": "safe-test"})
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 2
    assert route.call_count == 3
    tag = cache_write_barrier.tag_hash(domain="clinic-a", entity="client")
    assert await cache_write_barrier.read_generation(tag) is None


@pytest.mark.asyncio
async def test_overlapping_writes_hold_barrier_until_both_finish(monkeypatch, barrier_db):
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    tag = cache_write_barrier.tag_hash(domain="clinic-a", entity="client")
    await cache_write_barrier.begin_write(tag)
    await cache_write_barrier.begin_write(tag)
    await cache_write_barrier.finish_write(tag)
    assert await cache_write_barrier.read_generation(tag) is None
    await cache_write_barrier.finish_write(tag)
    assert await cache_write_barrier.read_generation(tag) == 2


@pytest.mark.asyncio
@respx.mock
async def test_pg_read_failure_bypasses_existing_cache(monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    value = {"version": 1}
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={
            "data": {"url": "https://clinic-a.vetmanager.cloud"}}))
    route = respx.get("https://clinic-a.vetmanager.cloud/rest/api/client").mock(
        side_effect=lambda _request: httpx.Response(200, json={"data": value.copy()}))
    reader = make_client_with_resolved_runtime("clinic-a", "test-key")
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 1
    value["version"] = 2
    async def unavailable(_tag):
        raise OSError("database unavailable")
    monkeypatch.setattr(cache_write_barrier, "read_generation", unavailable)
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 2
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_started_before_write_does_not_cache_old_result(
        monkeypatch, barrier_db):
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("WEB_SESSION_SECRET", "test-only-cache-barrier-secret")
    entered = asyncio.Event()
    release = asyncio.Event()
    value = {"version": 1}

    async def response(request):
        if request.method == "POST":
            value["version"] = 2
            return httpx.Response(200, json={"success": True})
        captured = value["version"]
        if not entered.is_set():
            entered.set()
            await release.wait()
        return httpx.Response(200, json={"data": {"version": captured}})

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json={
            "data": {"url": "https://clinic-a.vetmanager.cloud"}}))
    route = respx.route(url="https://clinic-a.vetmanager.cloud/rest/api/client",
                        method__in=["GET", "POST"]).mock(side_effect=response)
    reader = make_client_with_resolved_runtime("clinic-a", "test-key")
    writer = make_client_with_resolved_runtime("clinic-a", "test-key")
    pending = asyncio.create_task(reader.get("/rest/api/client"))
    await asyncio.wait_for(entered.wait(), 5)
    await writer.post("/rest/api/client", json={"name": "safe-test"})
    release.set()
    assert (await pending)["data"]["version"] == 1
    assert (await reader.get("/rest/api/client"))["data"]["version"] == 2
    assert route.call_count == 3
