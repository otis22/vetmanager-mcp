"""Opt-in devtr6 probe: real PostgreSQL restart after a completed upstream write."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import httpx
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from storage import Base, create_database_engine, normalize_database_url_for_migrations
from storage_models import Account, AccountFirstSession, VetmanagerCacheBarrier
from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api


def _wait_file(path: Path, seconds: float = 45) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(.05)
    raise TimeoutError(f"Stage 385 hook did not reach {path.name}")


@pytest.mark.skipif(not all(os.environ.get(name) for name in (
    "STAGE385_REDIS_URL", "STAGE385_PG_URL", "STAGE385_PG_HOOK_DIR", "TEST_API_KEY")),
    reason="isolated PostgreSQL and devtr6 contour absent")
def test_pg_restart_after_successful_upstream_write_never_serves_stale_get(monkeypatch):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    hook = Path(os.environ["STAGE385_PG_HOOK_DIR"])
    assert hook.is_dir() and not any(hook.iterdir())
    monkeypatch.setenv("DATABASE_URL", os.environ["STAGE385_PG_URL"])
    monkeypatch.setenv("WEB_SESSION_SECRET", "stage385-test-only-pg-secret")
    monkeypatch.setenv("STORAGE_ENCRYPTION_KEY", os.environ["STORAGE_ENCRYPTION_KEY"])
    engine = create_database_engine(os.environ["STAGE385_PG_URL"])

    async def create_schema():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await engine.dispose()

    asyncio.run(create_schema())
    token = seed_devtr6_bearer()
    anchor_engine = create_engine(normalize_database_url_for_migrations(os.environ["STAGE385_PG_URL"]))
    try:
        with Session(anchor_engine) as session:
            account_id = session.scalar(select(Account.id).where(
                Account.email == "stage384-load@example.test"))
            assert account_id is not None
            session.add(AccountFirstSession(
                account_id=account_id, first_token_issued_at=datetime.now(timezone.utc)))
            session.commit()
    finally:
        anchor_engine.dispose()
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text")
    processes = []
    clients = []
    client_id = None
    try:
        for slot, port in enumerate((_free_port(), _free_port(), _free_port())):
            slot_env = {**env, "PORT": str(port),
                        "STAGE385_PG_HOOK_SLOT": "writer" if slot == 0 else "reader"}
            processes.append(subprocess.Popen(
                [sys.executable, "-m", "tests.stage385_pg_hook_server"],
                cwd=Path(__file__).resolve().parents[1], env=slot_env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True))
            clients.append(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=45))
        for client, process in zip(clients, processes):
            for _ in range(100):
                if process.poll() is not None:
                    raise AssertionError("MCP slot exited before readiness")
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("MCP slot did not become ready")

        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json",
                   "MCP-Protocol-Version": "2025-03-26"}
        for client in clients:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-pg-recovery", "version": "1"}}})
            assert initialized.status_code == 200
            session_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=session_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"}).status_code in (200, 202)
            client.headers.update(session_headers)

        def call(slot: int, request_id: int, name: str, arguments: dict):
            response = clients[slot].post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}})
            body = _jsonrpc(response)
            assert response.status_code == 200
            assert "error" not in body and not body["result"].get("isError")
            return body["result"]["structuredContent"]

        def record(payload: dict) -> dict:
            item = payload["data"]["client"]
            return item[0] if isinstance(item, list) else item

        call(1, 8, "get_clients", {"limit": 1})
        sync_engine = create_engine(normalize_database_url_for_migrations(env["DATABASE_URL"]))
        try:
            with Session(sync_engine) as session:
                first_seen = session.get(AccountFirstSession, account_id).first_tool_success_at
                assert first_seen is not None
            call(0, 9, "get_clients", {"limit": 1})
            with Session(sync_engine) as session:
                assert session.get(AccountFirstSession, account_id).first_tool_success_at == first_seen
        finally:
            sync_engine.dispose()
        print("STAGE385_FIRST_SESSION", {"slots": 3, "http_codes": [200, 200],
              "one_durable_first_tool_event": True})

        marker = uuid.uuid4().hex[:12]
        created = call(0, 10, "create_client", {
            "first_name": f"Stage385-pg-{marker}", "last_name": "Probe"})
        client_id = int(record(created)["id"])
        before = call(1, 11, "get_client_by_id", {"client_id": client_id})
        assert record(before)["first_name"] == f"Stage385-pg-{marker}"
        (hook / "armed").touch()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(call, 0, 12, "update_client", {
                "client_id": client_id, "first_name": f"Stage385-pg-updated-{marker}"})
            _wait_file(hook / "entered")
            # Host orchestration stops only stage385turn7-pg, then releases us.
            _wait_file(hook / "release")
            future.result(timeout=45)
        (hook / "write_done").touch()
        _wait_file(hook / "restored")
        after = call(1, 13, "get_client_by_id", {"client_id": client_id})
        assert record(after)["first_name"] == f"Stage385-pg-updated-{marker}"
        sync_engine = create_engine(normalize_database_url_for_migrations(env["DATABASE_URL"]))
        try:
            with Session(sync_engine) as session:
                rows = session.scalars(select(VetmanagerCacheBarrier)).all()
                assert len(rows) == 1 and rows[0].active_writes == 1
        finally:
            sync_engine.dispose()
        print("STAGE385_PG_RECOVERY", {
            "slots": 3, "create_read_update_recovered_read": [200, 200, 200, 200],
            "upstream_write_completed_before_pg_stop": True,
            "durable_active_writes": 1, "stale_get": False})
    finally:
        if client_id is not None and (hook / "restored").exists():
            (hook / "armed").unlink(missing_ok=True)
            try:
                call(0, 14, "delete_client", {"client_id": client_id})
            except Exception:
                pass
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
