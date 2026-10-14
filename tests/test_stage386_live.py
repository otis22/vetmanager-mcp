"""Opt-in isolated three-slot MCP session recovery against shared Redis."""

import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port


pytestmark = pytest.mark.real_api


def _rejection_count(client, status, reason):
    response = client.get("/metrics")
    assert response.status_code == 200
    lines = [line for line in response.text.splitlines()
             if line.startswith('vetmanager_mcp_transport_rejections_total{')
             and f'status_code="{status}",reason="{reason}"' in line]
    assert len(lines) <= 1
    return int(lines[0].rsplit(" ", 1)[1]) if lines else 0


def _http_count(client, status):
    response = client.get("/metrics")
    assert response.status_code == 200
    lines = [line for line in response.text.splitlines()
             if line.startswith('vetmanager_http_requests_total{')
             and f'route="/mcp",method="POST",status_code="{status}"' in line]
    assert len(lines) <= 1
    return int(lines[0].rsplit(" ", 1)[1]) if lines else 0


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="isolated test contour absent")
def test_expired_session_and_reinitialize_on_three_slots(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    ports = [_free_port() for _ in range(3)]
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text")
    processes, clients = [], []
    try:
        for port in ports:
            env["PORT"] = str(port)
            processes.append(subprocess.Popen(
                [sys.executable, "-c", "from server import _run_http_server; import os; "
                 "_run_http_server(transport='streamable-http',host='127.0.0.1',"
                 "port=int(os.environ['PORT']),path='/mcp')"],
                cwd=Path(__file__).resolve().parents[1], env=env.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        for port, process in zip(ports, processes):
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
            clients.append(client)
            for _ in range(100):
                assert process.poll() is None, "isolated MCP slot exited"
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("isolated MCP slot not ready")
        before = [_rejection_count(client, 404, "session_not_found") for client in clients]
        before_http = _http_count(clients[0], 404)
        assert len(set(before)) == 1
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26"}
        stale = clients[0].post("/mcp", headers={**headers, "Mcp-Session-Id": str(uuid4())},
                                json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        assert stale.status_code == 404
        assert stale.json()["error"]["message"] == "Session not found"
        deadline = time.monotonic() + 5
        while True:
            after = [_rejection_count(client, 404, "session_not_found") for client in clients]
            after_http = [_http_count(client, 404) for client in clients]
            if (after == [before[0] + 1] * 3 and
                    after_http == [before_http + 1] * 3) or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        assert after == [before[0] + 1] * 3
        assert after_http == [before_http + 1] * 3
        fresh = clients[0].post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                       "clientInfo": {"name": "stage386-recovery", "version": "1"}},
        })
        assert fresh.status_code == 200
        assert fresh.headers.get("mcp-session-id")
        before_accept = _rejection_count(clients[0], 406, "invalid_accept")
        bad_accept = clients[0].post("/mcp", headers={**headers, "Accept": "application/json"},
                                     json={"jsonrpc": "2.0", "id": 3, "method": "initialize",
                                           "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                                                      "clientInfo": {"name": "stage386-recovery", "version": "1"}}})
        before_missing = _rejection_count(clients[0], 400, "missing_session")
        missing_session = clients[0].post("/mcp", headers=headers,
                                           json={"jsonrpc": "2.0", "id": 6,
                                                 "method": "tools/list"})
        assert bad_accept.status_code == 406
        assert "Not Acceptable: Client must accept" in bad_accept.text
        assert missing_session.status_code == 400
        assert "Bad Request: Missing session ID" in missing_session.text
        deadline = time.monotonic() + 5
        while True:
            accept_counts = [_rejection_count(client, 406, "invalid_accept")
                             for client in clients]
            missing_counts = [_rejection_count(client, 400, "missing_session")
                              for client in clients]
            if (accept_counts == [before_accept + 1] * 3 and
                    missing_counts == [before_missing + 1] * 3) or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        assert accept_counts == [before_accept + 1] * 3
        assert missing_counts == [before_missing + 1] * 3
        before_other = _rejection_count(clients[0], 400, "other")
        before_auth = _rejection_count(clients[0], 400, "missing_auth")
        poisoned_version = clients[0].post("/mcp", headers={
            **headers, "Mcp-Session-Id": fresh.headers["mcp-session-id"],
            "MCP-Protocol-Version": "missing_authorization"},
            json={"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
        assert poisoned_version.status_code == 400
        assert "Unsupported protocol version" in poisoned_version.text
        deadline = time.monotonic() + 5
        while True:
            other_counts = [_rejection_count(client, 400, "other") for client in clients]
            if other_counts == [before_other + 1] * 3 or time.monotonic() >= deadline:
                break
            time.sleep(.05)
        assert other_counts == [before_other + 1] * 3
        assert [_rejection_count(client, 400, "missing_auth") for client in clients] == [before_auth] * 3
        print("STAGE386_LIVE", {"stale_http": stale.status_code,
              "stale_error": stale.json()["error"]["message"],
              "counter_before": before, "counter_after": after,
              "reinitialize_http": fresh.status_code,
              "bad_accept_http": bad_accept.status_code, "invalid_accept": accept_counts,
              "missing_session_http": missing_session.status_code,
              "missing_session": missing_counts,
              "poisoned_version_http": poisoned_version.status_code,
              "poisoned_version_reason": other_counts})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
