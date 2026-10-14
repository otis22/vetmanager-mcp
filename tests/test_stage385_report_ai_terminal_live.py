"""Opt-in devtr6 Report AI terminal accounting through three MCP slots."""

import os
import hashlib
import hmac
import json
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest
import redis

from shared_metric_counters import REPORT_AI_TERMINAL_KEY_PREFIX
from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api


def _saved_terminal_count(body: str) -> float:
    prefix = 'vetmanager_report_ai_job_terminal_outcomes_total{outcome="saved"} '
    lines = [line for line in body.splitlines() if line.startswith(prefix)]
    assert len(lines) <= 1
    return float(lines[0].rsplit(" ", 1)[1]) if lines else 0.0


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_saved_job_terminal_count_once_across_slots(prepared_web_db):
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
                 "_run_http_server(transport='streamable-http',host='127.0.0.1',"
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
        for client in clients:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-terminal", "version": "1"}},
            })
            assert initialized.status_code == 200
            session_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=session_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            client.headers.update(session_headers)
        baseline = _saved_terminal_count(clients[0].get("/metrics").text)
        purpose_key = hmac.new(env["WEB_SESSION_SECRET"].encode(),
                               b"report-ai-observation-v1", hashlib.sha256).digest()
        identity = json.dumps([env["TEST_DOMAIN"], 2], separators=(",", ":")).encode()
        digest = hmac.new(purpose_key, identity, hashlib.sha256).hexdigest()
        prior_claim = bool(redis.Redis.from_url(env["STAGE385_REDIS_URL"]).exists(
            REPORT_AI_TERMINAL_KEY_PREFIX + digest))
        codes = []
        safe_bodies = []
        for client in clients:
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get_report_ai_job", "arguments": {"job_id": 2}},
            })
            result = _jsonrpc(response)
            codes.append(response.status_code)
            safe_bodies.append({"rpc_error": "error" in result,
                                "tool_error": result.get("result", {}).get("isError", False)})
            assert response.status_code == 200 and not safe_bodies[-1]["rpc_error"]
            assert not safe_bodies[-1]["tool_error"]
        after = [_saved_terminal_count(client.get("/metrics").text) for client in clients]
        expected_delta = 0 if prior_claim else 1
        assert after == [baseline + expected_delta] * 3
        print("STAGE385_REPORT_AI_TERMINAL", {"slots": 3, "http_codes": codes,
                                             "safe_bodies": safe_bodies,
                                             "prior_claim": prior_claim,
                                             "metric_delta": expected_delta})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
