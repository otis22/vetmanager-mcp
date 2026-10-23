"""Opt-in devtr6 write barrier probe through three independent MCP slots."""

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

from storage import normalize_database_url_for_migrations
from storage_models import VetmanagerCacheBarrier
from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_report_ai_write_commits_pg_barrier_before_cross_slot_read(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text")
    processes = []
    clients = []
    try:
        for port in (_free_port(), _free_port(), _free_port()):
            env["PORT"] = str(port)
            processes.append(subprocess.Popen(
                [sys.executable, "-c", "from server import _run_http_server; import os; "
                 "_run_http_server(stateless_http=False, transport='streamable-http',host='127.0.0.1',"
                 "port=int(os.environ['PORT']),path='/mcp')"],
                cwd=Path(__file__).resolve().parents[1], env=env.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            ))
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
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        }
        for client in clients:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-barrier", "version": "1"}},
            })
            assert initialized.status_code == 200
            session_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=session_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            client.headers.update(session_headers)

        created = clients[0].post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "create_report_ai_job", "arguments": {
                "intent_text": "Количество клиентов за январь 1900 года"}},
        })
        create_body = _jsonrpc(created)
        assert created.status_code == 200
        assert "error" not in create_body
        assert not create_body["result"]["isError"]
        job_id = create_body["result"]["structuredContent"]["data"]["job"]["id"]
        read = clients[1].post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call",
            "params": {"name": "get_report_ai_job", "arguments": {"job_id": job_id}},
        })
        read_body = _jsonrpc(read)
        assert read.status_code == 200 and "error" not in read_body
        assert not read_body["result"]["isError"]
        engine = create_engine(normalize_database_url_for_migrations(env["DATABASE_URL"]))
        try:
            with Session(engine) as session:
                barriers = session.scalars(select(VetmanagerCacheBarrier)).all()
                assert len(barriers) == 1
                assert barriers[0].generation == 1 and barriers[0].active_writes == 0
                assert len(barriers[0].tag_hash) == 64
        finally:
            engine.dispose()
        print("STAGE385_CACHE_BARRIER", {
            "slots": 3, "http_codes": [created.status_code, read.status_code],
            "safe_bodies": {"create_error": False, "read_error": False},
            "generation": 1, "active_writes": 0,
        })

        # Read on B first so it holds an old cache entry; update on A must
        # advance the shared generation before B serves that entry again.
        marker = uuid.uuid4().hex[:12]
        client_id = None
        def record(payload: dict) -> dict:
            clients_data = payload["data"]["client"]
            return clients_data[0] if isinstance(clients_data, list) else clients_data
        def call(slot: int, request_id: int, name: str, arguments: dict):
            response = clients[slot].post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
            body = _jsonrpc(response)
            assert response.status_code == 200
            assert "error" not in body and not body["result"].get("isError")
            return response.status_code, body["result"]["structuredContent"]
        try:
            create_code, created_client = call(0, 10, "create_client", {
                "first_name": f"Stage385-{marker}", "last_name": "Probe"})
            client_id = int(record(created_client)["id"])
            old_code, old_client = call(1, 11, "get_client_by_id", {"client_id": client_id})
            assert record(old_client)["first_name"] == f"Stage385-{marker}"
            update_code, _ = call(0, 12, "update_client", {
                "client_id": client_id, "first_name": f"Stage385-updated-{marker}"})
            new_code, new_client = call(1, 13, "get_client_by_id", {"client_id": client_id})
            assert record(new_client)["first_name"] == f"Stage385-updated-{marker}"
            print("STAGE385_CROSS_SLOT_ENTITY", {
                "slots": 3, "http_codes": [create_code, old_code, update_code, new_code],
                "changed": True, "stale_get": False,
            })
        finally:
            if client_id is not None:
                call(0, 14, "delete_client", {"client_id": client_id})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
