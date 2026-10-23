"""Opt-in devtr6 Report export outcome dedup across three MCP slots."""

import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api


def _success_count(body: str) -> int:
    prefix = 'vetmanager_report_ai_exports_total{operation="poll",outcome="success"} '
    rows = [line for line in body.splitlines() if line.startswith(prefix)]
    assert len(rows) <= 1
    return int(rows[0].rsplit(" ", 1)[1]) if rows else 0


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_export_poll_success_is_one_outcome_across_slots(prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    env = os.environ.copy()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text",
               SITE_BASE_URL="https://stage385.invalid")
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
        for client in clients:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-export", "version": "1"}},
            })
            assert initialized.status_code == 200
            session_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=session_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            client.headers.update(session_headers)
        before = clients[0].get("/metrics")
        assert before.status_code == 200
        baseline = _success_count(before.text)
        report_id = int(os.environ.get("REPORT_EXPORT_PROBE_REPORT_ID", "84"))
        start = clients[0].post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "start_report_export", "arguments": {"report_id": report_id}},
        })
        assert start.status_code == 200
        started = _jsonrpc(start)
        if started.get("result", {}).get("isError"):
            pytest.skip("Devtr6 export guard refused this safe test report")
        content = started.get("result", {}).get("structuredContent", {})
        file_id = content.get("data", {}).get("report", {}).get("report_file_id")
        assert isinstance(file_id, int) or isinstance(file_id, str) and file_id.isdecimal()
        success_codes = []
        download_path = None
        for _ in range(12):
            response = clients[1].post("/mcp", json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "get_report_export_download",
                           "arguments": {"report_file_id": int(file_id)}},
            })
            assert response.status_code == 200
            if not _jsonrpc(response).get("result", {}).get("isError"):
                success_codes.append(response.status_code)
                content = _jsonrpc(response).get("result", {}).get("structuredContent", {})
                download_url = content.get("download_url")
                assert isinstance(download_url, str)
                assert download_url.startswith("https://stage385.invalid/report-export/")
                download_path = urlsplit(download_url).path
                break
            time.sleep(5)
        if not success_codes:
            pytest.skip("Devtr6 export build did not finish in the test window")
        duplicate = clients[2].post("/mcp", json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/call",
            "params": {"name": "get_report_export_download",
                       "arguments": {"report_file_id": int(file_id)}},
        })
        assert duplicate.status_code == 200
        assert not _jsonrpc(duplicate).get("result", {}).get("isError")
        assert download_path is not None
        downloads = [client.get(download_path) for client in (clients[0], clients[2])]
        assert [response.status_code for response in downloads] == [200, 200]
        assert all(response.headers.get("content-type", "").startswith("text/csv")
                   for response in downloads)
        assert downloads[0].content and downloads[0].content == downloads[1].content
        after = [client.get("/metrics") for client in clients]
        assert [response.status_code for response in after] == [200] * 3
        assert [_success_count(response.text) for response in after] == [baseline + 1] * 3
        print("STAGE385_EXPORT_OUTCOME", {"slots": 3, "start_http": start.status_code,
                                          "poll_http": success_codes + [duplicate.status_code],
                                          "download_http": [200, 200],
                                          "same_file": True,
                                          "success_delta": 1,
                                          "safe_bodies": {"start_error": False,
                                                          "poll_error": False}})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
