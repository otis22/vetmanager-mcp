"""Opt-in devtr6 empty-preview guidance across three MCP slots."""

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


def _metric(body: str, prefix: str) -> float:
    lines = [line for line in body.splitlines() if line.startswith(prefix)]
    assert len(lines) <= 1
    return float(lines[0].rsplit(" ", 1)[1]) if lines else 0.0


@pytest.mark.skipif(not os.environ.get("STAGE385_REDIS_URL") or
                    not os.environ.get("TEST_API_KEY"), reason="stage 385 live contour absent")
def test_empty_preview_guidance_and_recreated_outcome_cross_slots(prepared_web_db):
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
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True))
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
        headers = {"Authorization": f"Bearer {token}",
                   "Accept": "application/json, text/event-stream",
                   "Content-Type": "application/json",
                   "MCP-Protocol-Version": "2025-03-26"}
        for client in clients:
            initialized = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize",
                "params": {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "stage385-guidance", "version": "1"}}})
            assert initialized.status_code == 200
            slot_headers = {**headers, "Mcp-Session-Id": initialized.headers["mcp-session-id"]}
            assert client.post("/mcp", headers=slot_headers, json={
                "jsonrpc": "2.0", "method": "notifications/initialized"}).status_code in (200, 202)
            client.headers.update(slot_headers)

        def call(slot: int, request_id: int, name: str, arguments: dict):
            response = clients[slot].post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": name, "arguments": arguments}})
            body = _jsonrpc(response)
            assert response.status_code == 200
            assert "error" not in body and not body["result"].get("isError")
            return body["result"]["structuredContent"]

        before = _metric(clients[0].get("/metrics").text,
                         "vetmanager_report_ai_empty_preview_guidance_jobs_total ")
        before_recreated = _metric(clients[0].get("/metrics").text,
            'vetmanager_report_ai_empty_preview_guidance_outcomes_total{outcome="recreated"} ')
        intent = ("Покажи список медицинских карт за 1 января 1900 года: "
                  "ID карты, дату и ID клиники. Дата строго 01.01.1900.")
        created = call(0, 10, "create_report_ai_job", {"intent_text": intent})
        job = created["data"]["job"]
        for attempt in range(42):
            if job.get("status") in {"ready_to_save", "failed", "rejected"}:
                break
            time.sleep(10)
            observed = call(1 + attempt % 2, 11 + attempt, "get_report_ai_job",
                            {"job_id": job["id"]})
            job = observed["data"]["job"]
        assert job.get("status") == "ready_to_save"
        assert (job.get("mcp_empty_preview_guidance") or {}).get("code") == "report_ai_empty_preview"
        after = [_metric(client.get("/metrics").text,
                         "vetmanager_report_ai_empty_preview_guidance_jobs_total ")
                 for client in clients]
        assert after == [before + 1] * 3
        call(2, 60, "create_report_ai_job", {"intent_text":
             "Количество медицинских карт за 2 января 1900 года по клиникам"})
        outcomes = [_metric(client.get("/metrics").text,
            'vetmanager_report_ai_empty_preview_guidance_outcomes_total{outcome="recreated"} ')
            for client in clients]
        assert outcomes == [before_recreated + 1] * 3
        print("STAGE385_GUIDANCE", {"slots": 3, "http_codes": [200, 200, 200],
              "guidance_code": "report_ai_empty_preview",
              "issued_jobs_delta": 1, "recreated_delta": 1,
              "equal_metrics": True})
    finally:
        for client in clients:
            client.close()
        for process in processes:
            process.terminate()
        for process in processes:
            process.wait(timeout=30)
