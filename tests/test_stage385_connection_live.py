"""Opt-in devtr6 connection saves from independent PostgreSQL worker processes."""

import asyncio
from multiprocessing import get_context
import os
import uuid

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from storage import Base, create_database_engine, normalize_database_url_for_migrations
from storage_models import Account, VetmanagerConnection


pytestmark = pytest.mark.real_api


def _save_in_slot(account_id: int, ready, release, result_queue) -> None:
    from storage import get_session_factory
    from vetmanager_connection_service import save_domain_api_key_connection

    async def run():
        async with get_session_factory()() as session:
            return await save_domain_api_key_connection(
                session, account_id=account_id, domain=os.environ["TEST_DOMAIN"],
                api_key=os.environ["TEST_API_KEY"],
                encryption_key=os.environ["STORAGE_ENCRYPTION_KEY"])

    ready.set()
    if not release.wait(10):
        result_queue.put({"ok": False, "reason": "start timeout"})
        return
    try:
        connection = asyncio.run(run())
        result_queue.put({"ok": True, "connection_id": connection.id})
    except Exception as exc:
        result_queue.put({"ok": False, "reason": type(exc).__name__})


@pytest.mark.skipif(not os.environ.get("STAGE385_PG_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="isolated PG/devtr6 absent")
def test_two_slots_save_one_account_without_lost_connection(monkeypatch):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    monkeypatch.setenv("DATABASE_URL", os.environ["STAGE385_PG_URL"])
    monkeypatch.setenv("MCP_WORKER_SLOTS", "3")
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "5")
    engine = create_database_engine(os.environ["STAGE385_PG_URL"])

    async def prepare():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(prepare())
    sync_engine = create_engine(normalize_database_url_for_migrations(os.environ["STAGE385_PG_URL"]))
    try:
        with Session(sync_engine) as session:
            account = Account(email=f"stage385-{uuid.uuid4().hex}@example.test", status="active")
            session.add(account)
            session.commit()
            account_id = account.id
        context = get_context("spawn")
        result_queue = context.Queue()
        ready = [context.Event(), context.Event()]
        release = context.Event()
        processes = [context.Process(target=_save_in_slot,
                                     args=(account_id, signal, release, result_queue))
                     for signal in ready]
        try:
            for process in processes:
                process.start()
            assert all(signal.wait(10) for signal in ready)
            release.set()
            results = [result_queue.get(timeout=70) for _ in processes]
            assert all(result["ok"] for result in results), results
        finally:
            release.set()
            for process in processes:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
            assert all(process.exitcode == 0 for process in processes)
        with Session(sync_engine) as session:
            rows = session.scalars(select(VetmanagerConnection).where(
                VetmanagerConnection.account_id == account_id)).all()
            active = [row for row in rows if row.status == "active"]
            assert len(rows) == 2 and len(active) == 1
            assert active[0].get_credentials(
                encryption_key=os.environ["STORAGE_ENCRYPTION_KEY"])["domain"] == "devtr6"
        print("STAGE385_CONNECTION_SAVE", {
            "worker_processes": 2, "slot_configuration": 3,
            "successful_validations": 2, "connections": 2, "active": 1,
            "credentials_preserved": True})
    finally:
        sync_engine.dispose()
