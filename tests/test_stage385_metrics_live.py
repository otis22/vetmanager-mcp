"""Opt-in devtr6 tool counter check through three independent MCP processes."""

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


pytestmark = pytest.mark.real_api


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _jsonrpc(response: httpx.Response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: "))
    return response.json()


def _tool_counter(body: str) -> int:
    lines = [line for line in body.splitlines()
             if line.startswith("vetmanager_tool_calls_total{")
             and 'endpoint="/rest/api/client#list"' in line
             and 'tool="client.list"' in line
             and 'method="GET"' in line
             and 'outcome="success"' in line]
    if not lines:
        assert not any(line.startswith("vetmanager_tool_calls_total{") for line in body.splitlines()), [
            line for line in body.splitlines() if line.startswith("vetmanager_tool_calls_total{")][:8]
        return 0
    assert len(lines) == 1
    return int(lines[0].rsplit(" ", 1)[1])


def _metrics(client: httpx.Client) -> int:
    response = client.get("/metrics")
    assert response.status_code == 200, response.text[:200]
    return _tool_counter(response.text)


def _metric_value(body: str, prefix: str, *, required: str = "") -> float:
    lines = [line for line in body.splitlines()
             if line.startswith(prefix) and required in line]
    assert len(lines) == 1, prefix
    return float(lines[0].rsplit(" ", 1)[1])


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_three_slots_export_one_devtr6_tool_count(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    processes = []
    ports = [_free_port() for _ in range(3)]
    env = os.environ.copy()
    env["REDIS_URL"] = env["STAGE385_REDIS_URL"]
    env["MCP_WORKER_SLOTS"] = "3"
    env["DB_POOL_SIZE"] = "8"
    env["DB_MAX_OVERFLOW"] = "5"
    env["LOG_FORMAT"] = "text"
    clients = []
    try:
        for port in ports:
            env["PORT"] = str(port)
            processes.append(subprocess.Popen(
                [sys.executable, "-c", "from server import _run_http_server; import os; "
                 "_run_http_server(transport='streamable-http',host='127.0.0.1',"
                 "port=int(os.environ['PORT']),path='/mcp')"],
                cwd=Path(__file__).resolve().parents[1], env=env.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            ))
        for port, process in zip(ports, processes):
            client = httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30)
            clients.append(client)
            for _ in range(100):
                if process.poll() is not None:
                    detail = process.stderr.read()[-1200:] if process.stderr else ""
                    raise AssertionError(f"MCP slot exited before readiness: {detail}")
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
                           "clientInfo": {"name": "stage385-metrics", "version": "1"}},
            })
            assert initialized.status_code == 200
            slot_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=slot_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            client.headers.update(slot_headers)
        baseline = [_metrics(client) for client in clients]
        assert len(set(baseline)) == 1
        codes = []
        for client in clients:
            for request_id in range(3):
                response = client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": request_id + 10, "method": "tools/call",
                    "params": {"name": "get_clients", "arguments": {"limit": 1}},
                })
                payload = _jsonrpc(response)
                assert response.status_code == 200
                assert "error" not in payload and not payload["result"].get("isError")
                codes.append(response.status_code)
        after = [_metrics(client) for client in clients]
        assert after == [baseline[0] + 9] * 3
        rendered = [client.get("/metrics").text for client in clients]
        latency_counts = [_metric_value(body, "vetmanager_tool_call_latency_seconds_count{",
                                        required='endpoint="/rest/api/client#list"')
                          for body in rendered]
        assert len(set(latency_counts)) == 1 and latency_counts[0] >= 9
        cache_hits = [_metric_value(body, "vetmanager_cache_hits_total ") for body in rendered]
        cache_entries = [_metric_value(body, "vetmanager_cache_entries ") for body in rendered]
        assert len(set(cache_hits)) == 1 and cache_hits[0] >= 6
        assert len(set(cache_entries)) == 1 and cache_entries[0] >= 3
        print("STAGE385_METRICS", {"slots": 3, "tool_calls": len(codes),
                                    "tool_http": sorted(set(codes)), "metric_delta": 9,
                                    "equal_snapshots": len(set(after)) == 1,
                                    "latency_count": latency_counts[0],
                                    "cache_hits_min": cache_hits[0],
                                    "cache_entries_min": cache_entries[0]})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
