"""Opt-in real devtr6 MCP read across a guaranteed process restart."""

import json
import os
from pathlib import Path
import subprocess
import sys
import time

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer
from scripts.stage385_deploy import _stateless_protocol_ready


pytestmark = pytest.mark.real_api


def _payload(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: "))
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 credentials absent")
def test_devtr6_stateless_tool_survives_process_restart(prepared_web_db, free_tcp_port):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    token = seed_devtr6_bearer()
    base = f"http://127.0.0.1:{free_tcp_port}"
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-03-26"}
    env = {**os.environ, "PORT": str(free_tcp_port)}
    command = [sys.executable, "-c", "from server import _run_http_server; import os; "
               "_run_http_server(transport='streamable-http',host='127.0.0.1',"
               "port=int(os.environ['PORT']),path='/mcp')"]

    def start():
        process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1],
                                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with httpx.Client(base_url=base, timeout=5) as client:
            for _ in range(100):
                assert process.poll() is None, "MCP worker exited"
                try:
                    if client.get("/healthz").status_code == 200:
                        return process
                except httpx.TransportError:
                    pass
                time.sleep(.1)
        raise AssertionError("MCP worker did not start")

    def stop(process):
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    first_process = start()
    _stateless_protocol_ready(free_tcp_port)
    second_process = None
    try:
        with httpx.Client(base_url=base, timeout=30, headers=headers) as client:
            initialized = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "stage431-live", "version": "1"}}})
            assert initialized.status_code == 200
            assert "mcp-session-id" not in initialized.headers
            assert "protocolVersion" in _payload(initialized)["result"]
            notification = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert notification.status_code == 202
            call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": "get_pet_types", "arguments": {}}}
            before = client.post("/mcp", json=call)
            assert before.status_code == 200
            assert not _payload(before)["result"].get("isError")
        stop(first_process)
        first_process = None
        second_process = start()
        _stateless_protocol_ready(free_tcp_port)
        with httpx.Client(base_url=base, timeout=30, headers=headers) as client:
            after = client.post("/mcp", headers={"Mcp-Session-Id": "old-worker-session"}, json=call)
            assert after.status_code == 200
            assert not _payload(after)["result"].get("isError")
            no_id = client.post("/mcp", json=call)
            assert no_id.status_code == 200
            assert not _payload(no_id)["result"].get("isError")
            denied = client.post("/mcp", headers={"Authorization": ""}, json=call)
            assert denied.status_code in (200, 401, 403)
            if denied.status_code == 200:
                assert _payload(denied)["result"].get("isError")
            assert client.get("/mcp").status_code == 405
            assert client.get("/healthz").status_code == 200
            assert client.get("/metrics").status_code == 200
        smoke = subprocess.run(
            [sys.executable, "scripts/post_deploy_mcp_tool_smoke.py", base],
            cwd=Path(__file__).resolve().parents[1],
            env={**env, "PROD_SMOKE_BEARER_TOKEN": token},
            capture_output=True, text=True, timeout=60, check=False,
        )
        assert smoke.returncode == 0, smoke.stderr
        def body_shape(response):
            body = _payload(response)
            result = body.get("result", {})
            if "protocolVersion" in result:
                result = {"protocolVersion": result["protocolVersion"]}
            else:
                result = {"isError": result.get("isError"),
                          "structuredContent_keys": sorted(result.get("structuredContent", {}))}
            return {"jsonrpc": body.get("jsonrpc"), "id": body.get("id"), "result": result}

        print("STAGE431_LIVE", json.dumps({
            "initialize": [initialized.status_code, body_shape(initialized)],
            "notification": [notification.status_code, notification.text],
            "before": [before.status_code, body_shape(before)],
            "after_stale": [after.status_code, body_shape(after)],
            "after_no_id": [no_id.status_code, body_shape(no_id)],
            "without_bearer": [denied.status_code,
                               body_shape(denied) if denied.status_code == 200 else {"error": "unauthorized"}],
            "post_deploy_smoke": [smoke.returncode, smoke.stdout.strip()],
        }, ensure_ascii=False))
    finally:
        for process in (first_process, second_process):
            if process is not None and process.poll() is None:
                stop(process)
