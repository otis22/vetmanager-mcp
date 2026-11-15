"""Opt-in devtr6 Report export outcome dedup across three MCP slots."""

import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

import httpx
import pytest

from tests.child_process_env import make_test_server_env
import tests.export_shared  # noqa: F401
from tests.live_test_lifecycle import stop_processes
from tests.stage385_readiness import Stage385ReadinessTrace

from tests.test_stage384_live import seed_devtr6_bearer
from tests.test_stage385_metrics_live import _free_port, _jsonrpc


pytestmark = pytest.mark.real_api
pytest_plugins = ("tests.export_shared",)


def _success_count(body: str) -> int:
    prefix = 'vetmanager_report_ai_exports_total{operation="poll",outcome="success"} '
    rows = [line for line in body.splitlines() if line.startswith(prefix)]
    assert len(rows) <= 1
    return int(rows[0].rsplit(" ", 1)[1]) if rows else 0


def _safe_export_start_refusal(payload: dict) -> str:
    """Return a fixed error class without persisting an upstream response body."""
    result = payload.get("result", {})
    structured = result.get("structuredContent") or {}
    code = structured.get("error_code") if isinstance(structured, dict) else None
    if code in {"CONSTRUCTOR_BUSY", "RUN_RATE_LIMITED"}:
        return code
    content = result.get("content") or []
    text = " ".join(item.get("text", "") for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str))
    for guard_code in ("CONSTRUCTOR_BUSY", "RUN_RATE_LIMITED"):
        if guard_code in text:
            return guard_code
    if "tenant-wide REST export guard" in text:
        return "TENANT_GUARD"
    return "OTHER_ERROR"


def _safe_export_poll_error(payload: dict) -> str:
    """Recognize only bounded, retryable file-build states; never echo error text."""
    result = payload.get("result", {})
    structured = result.get("structuredContent") or {}
    code = structured.get("error_code") if isinstance(structured, dict) else None
    if code in {"FILE_BUILD_NOT_STARTED", "FILE_NOT_READY"}:
        return code
    content = result.get("content") or []
    text = " ".join(item.get("text", "") for item in content
                    if isinstance(item, dict) and isinstance(item.get("text"), str))
    for retryable in ("FILE_BUILD_NOT_STARTED", "FILE_NOT_READY"):
        if retryable in text:
            return retryable
    if "not ready" in text.lower() and "export" in text.lower():
        return "NOT_READY"
    return "OTHER_ERROR"


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_export_poll_success_is_one_outcome_across_slots(prepared_web_db, shared_live_export):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    file_id = shared_live_export.require_file_id()
    token = seed_devtr6_bearer()
    env = make_test_server_env()
    env.update(REDIS_URL=env["STAGE385_REDIS_URL"], MCP_WORKER_SLOTS="3",
               DB_POOL_SIZE="8", DB_MAX_OVERFLOW="5", LOG_FORMAT="text",
               SITE_BASE_URL="https://stage385.invalid")
    processes = []
    clients = []
    ports = []
    trace = Stage385ReadinessTrace("stage385-export")
    try:
        ports = [_free_port(), _free_port(), _free_port()]
        for index, port in enumerate(ports):
            env["PORT"] = str(port)
            env["STAGE385_PHASE_LABEL"] = "stage385-export"
            env["STAGE385_SLOT_INDEX"] = str(index)
            processes.append(subprocess.Popen(
                [sys.executable, "-c", "from tests.stage385_child_phase import run; run()"],
                cwd=Path(__file__).resolve().parents[1], env=env.copy(),
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
            ))
            clients.append(httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30))
        trace.wait_for_slots(clients, processes, ports)
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
        success_codes = []
        download_path = None
        last_poll_code = None
        for _ in range(12):
            response = clients[1].post("/mcp", json={
                "jsonrpc": "2.0", "id": 3, "method": "tools/call",
                "params": {"name": "get_report_export_download",
                           "arguments": {"report_file_id": int(file_id)}},
            })
            assert response.status_code == 200
            polled = _jsonrpc(response)
            if polled.get("result", {}).get("isError"):
                last_poll_code = _safe_export_poll_error(polled)
                if last_poll_code == "OTHER_ERROR":
                    pytest.fail("Devtr6 export poll returned a non-retryable error; raw response kept private")
                time.sleep(5)
                continue
            if not polled.get("result", {}).get("isError"):
                success_codes.append(response.status_code)
                content = polled.get("result", {}).get("structuredContent", {})
                download_url = content.get("download_url")
                assert isinstance(download_url, str)
                assert download_url.startswith("https://stage385.invalid/report-export/")
                download_path = urlsplit(download_url).path
                break
        if not success_codes:
            pytest.fail(f"Devtr6 export build did not finish in the test window: {last_poll_code}")
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
        print("STAGE385_EXPORT_OUTCOME", {"slots": 3, "shared_start": "success",
                                          "poll_http": success_codes + [duplicate.status_code],
                                          "download_http": [200, 200],
                                          "same_file": True,
                                          "success_delta": 1,
                                          "safe_bodies": {"start_error": False,
                                                          "poll_error": False}})
    finally:
        for client in clients:
            client.close()
        trace.capture_unprobed(processes, ports)
        trace.finish(stop_processes(processes))
