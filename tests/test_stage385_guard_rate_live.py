"""Opt-in devtr6 guard and Redis rate-limit counters across MCP slots."""

import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api


def _counter(body: str, prefix: str, labels: str) -> int:
    lines = [line for line in body.splitlines()
             if line.startswith(prefix) and labels in line]
    return int(lines[0].rsplit(" ", 1)[1]) if lines else 0


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_guard_and_rate_limit_events_are_shared(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text",
               RATE_LIMIT_REQUIRE_REDIS="1", OAUTH_TOKEN_RATE_LIMIT_ATTEMPTS="1")
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
            clients.append(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30))
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
        for client in clients[:2]:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-guard", "version": "1"}},
            })
            assert initialized.status_code == 200
            session_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=session_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            client.headers.update(session_headers)
        before = clients[2].get("/metrics")
        assert before.status_code == 200
        guard_before = _counter(before.text,
            "vetmanager_placeholder_argument_rejections_total{", 'tool="get_clients"')
        rate_before = _counter(before.text,
            "vetmanager_auth_failures_total{", 'source="web_rate_limit",reason="oauth_token"')
        guard_codes = []
        for client in clients[:2]:
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get_clients",
                           "arguments": {"name": "[client:123:last_name]"}},
            })
            guard_codes.append(response.status_code)
            assert response.status_code == 200
            assert _jsonrpc(response).get("result", {}).get("isError") is True
        rate_codes = []
        for client in clients[:2]:
            response = client.post(
                "/oauth/token", data={"grant_type": "stage385_invalid"},
                headers={"Content-Type": "application/x-www-form-urlencoded"})
            rate_codes.append(response.status_code)
            assert response.json().get("error") in {"unsupported_grant_type", "invalid_request",
                                                   "temporarily_unavailable"}
        assert rate_codes == [400, 429]
        after = [client.get("/metrics") for client in clients]
        assert [response.status_code for response in after] == [200] * 3
        assert [_counter(response.text, "vetmanager_placeholder_argument_rejections_total{",
                         'tool="get_clients"') for response in after] == [guard_before + 2] * 3
        assert [_counter(response.text, "vetmanager_auth_failures_total{",
                         'source="web_rate_limit",reason="oauth_token"')
                for response in after] == [rate_before + 1] * 3
        print("STAGE385_GUARD_RATE", {"slots": 3, "guard_http": guard_codes,
                                      "rate_http": rate_codes, "guard_delta": 2,
                                      "rate_delta": 1})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
