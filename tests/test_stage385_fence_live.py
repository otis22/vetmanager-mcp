"""Opt-in devtr6 bearer check of quiescence before an MCP tool reaches upstream."""

import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 credentials absent")
def test_devtr6_bearer_write_is_refused_after_quiesce(prepared_web_db, free_tcp_port):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    env = os.environ.copy()
    env.update(PORT=str(free_tcp_port), LOG_FORMAT="text")
    server = subprocess.Popen(
        [sys.executable, "-c", "from server import _run_http_server; import os; "
         "_run_http_server(transport='streamable-http',host='127.0.0.1',"
         "port=int(os.environ['PORT']),path='/mcp')"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    base = f"http://127.0.0.1:{free_tcp_port}"
    sse_started = threading.Event()
    sse_ended = threading.Event()
    observed = {}
    try:
        with httpx.Client(base_url=base, timeout=15) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise AssertionError("server exited before readiness")
                try:
                    if client.get("/readyz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("server did not become ready")
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-03-26",
            }
            initialize = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-fence", "version": "1"}},
            })
            assert initialize.status_code == 200
            headers["Mcp-Session-Id"] = initialize.headers["mcp-session-id"]
            assert client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)

            def hold_sse():
                try:
                    sse_headers = {**headers, "Accept": "text/event-stream"}
                    with httpx.Client(timeout=None) as stream_client:
                        with stream_client.stream("GET", base + "/mcp", headers=sse_headers) as stream:
                            observed["sse_status"] = stream.status_code
                            sse_started.set()
                            for _ in stream.iter_lines():
                                pass
                finally:
                    sse_ended.set()

            threading.Thread(target=hold_sse, daemon=True).start()
            assert sse_started.wait(10) and observed["sse_status"] == 200
            server.send_signal(signal.SIGUSR1)
            for _ in range(100):
                if client.get("/readyz").status_code == 503:
                    break
                time.sleep(.01)
            else:
                raise AssertionError("quiesce did not close readiness")
            refused = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "get_clients", "arguments": {"limit": 1}},
            })
            assert refused.status_code == 503
            assert refused.json() == {"error": "worker_draining", "retryable": True}
            server.send_signal(signal.SIGUSR2)
            assert sse_ended.wait(5)
            print("STAGE385_FENCE", {"initialize": 200, "ready_after_quiesce": 503,
                                     "tool_after_quiesce": 503, "body": refused.json(),
                                     "sse_closed_before_sigterm": True})
    finally:
        if server.poll() is None:
            server.send_signal(signal.SIGTERM)
        server.communicate(timeout=30)
