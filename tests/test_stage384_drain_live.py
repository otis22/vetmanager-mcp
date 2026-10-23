"""Live SIGTERM guard for the Server.run() boot path with a held GET SSE stream."""

import os
from pathlib import Path
import re
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
def test_devtr6_held_get_sse_drains_on_sigterm(prepared_web_db, free_tcp_port):
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    env = os.environ.copy()
    env.update(PORT=str(free_tcp_port), FASTMCP_LOG_LEVEL="INFO", LOG_FORMAT="text",
               STREAMABLE_HTTP_DRAIN_ENABLED="true")
    server = subprocess.Popen(
        [sys.executable, "-c", "from server import _run_http_server; "
         "import os; _run_http_server(stateless_http=False, transport='streamable-http',host='127.0.0.1',"
         "port=int(os.environ['PORT']),path='/mcp')"],
        cwd=Path(__file__).resolve().parents[1], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    base = f"http://127.0.0.1:{free_tcp_port}"
    started = threading.Event()
    ended = threading.Event()
    observed = {}
    try:
        with httpx.Client(base_url=base, timeout=5) as client:
            for _ in range(100):
                if server.poll() is not None:
                    raise AssertionError("server exited before health check")
                try:
                    if client.get("/healthz").status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(.1)
            else:
                raise AssertionError("health check did not become ready")
            assert client.get("/readyz").status_code == 200
            headers = {
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-03-26",
            }
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage384-drain", "version": "1"}},
            })
            assert response.status_code == 200
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
            assert client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)

        def hold_get():
            try:
                with httpx.Client(timeout=None) as client:
                    headers["Accept"] = "text/event-stream"
                    with client.stream("GET", base + "/mcp", headers=headers) as response:
                        observed["status"] = response.status_code
                        observed["type"] = response.headers.get("content-type", "")
                        started.set()
                        for _ in response.iter_lines():
                            pass
            except httpx.TransportError as exc:
                observed["end_class"] = type(exc).__name__
            finally:
                ended.set()

        thread = threading.Thread(target=hold_get, daemon=True)
        thread.start()
        assert started.wait(10)
        assert observed["status"] == 200 and "text/event-stream" in observed["type"]
        time.sleep(.5)
        start = time.monotonic()
        server.send_signal(signal.SIGTERM)
        _, logs = server.communicate(timeout=44)
        elapsed = time.monotonic() - start
        assert ended.wait(1)
        # Uvicorn re-raises captured SIGTERM after graceful shutdown outside PID 1.
        assert server.returncode in (0, -signal.SIGTERM) and elapsed < 45
        assert "Application shutdown complete." in logs
        assert any(
            "event_name=http_event_loop_selected" in line
            and "loop_module=uvloop" in line and "loop_class=Loop" in line
            for line in logs.splitlines()
        )
        assert re.search(r"event_name=streamable_http_drain_finished .*session_count=[1-9]", logs)
        print("STAGE384_DRAIN", {"health": 200, "ready": 200, "initialize": 200,
                                 "get_sse": observed["status"], "closed": True,
                                 "session_count_at_least_one": True, "shutdown_seconds": round(elapsed, 3)})
    finally:
        if server.poll() is None:
            server.kill()
            server.communicate(timeout=5)
