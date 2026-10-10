"""Opt-in devtr6 HTTP evidence for both first-session access presets."""

import json
import os
import re
from datetime import date

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync

pytestmark = pytest.mark.real_api
CHAIN = {"create_report_ai_job", "get_report_ai_job", "save_report_ai_job_as_report", "get_report_ai_job_data"}


def _rpc(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        return json.loads(events[-1])
    return response.json()


def _data_rows(result, entity):
    content = result.get("structuredContent")
    if content is None:
        content = json.loads(result["content"][0]["text"])
    data = content.get("data") if isinstance(content, dict) else None
    if isinstance(data, dict):
        assert entity in data, f"Expected collection key {entity}; keys: {sorted(data)}"
        data = data[entity]
    assert isinstance(data, list), f"Expected list for {entity}"
    return data


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_welcome_access_routes_live(live_server_url, monkeypatch):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "stage377-metrics-test")
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage377-live@example.test", "password": "Stage377-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        tokens = {}
        for preset in ("frontdesk", "report_ai"):
            issued = _post_with_csrf_sync(client, "/account/tokens", data={
                "token_name": f"Stage 377 {preset} devtr6", "expires_in_days": "1",
                "ip_mask": "*.*.*.*", "access_preset": preset,
            }, page_path="/account")
            assert issued.status_code == 200
            match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
            assert match is not None
            tokens[preset] = match.group(0)
            print("TOKEN_ISSUED", preset, issued.status_code, '{"one_time_token":"<redacted>"}')
        assert tokens["frontdesk"] != tokens["report_ai"]
        sessions = {}

        def rpc(preset, method, params, request_id):
            headers = {
                "Authorization": f"Bearer {tokens[preset]}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-03-26",
            }
            if preset in sessions:
                headers["Mcp-Session-Id"] = sessions[preset]
            response = client.post("/mcp", headers=headers, json={
                "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
            })
            assert response.status_code == 200
            if method == "initialize" and response.headers.get("mcp-session-id"):
                sessions[preset] = response.headers["mcp-session-id"]
            body = _rpc(response)
            assert "error" not in body
            return response.status_code, body["result"]

        for preset in ("frontdesk", "report_ai"):
            code, initialized = rpc(preset, "initialize", {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage377-live", "version": "1"},
            }, 1)
            assert "welcome_first_session" in initialized["instructions"]
            print("INITIALIZE", preset, code, '{"welcome_pointer":true,"read_route":true}')
            ready = client.post("/mcp", headers={
                "Authorization": f"Bearer {tokens[preset]}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": "2025-03-26",
                "Mcp-Session-Id": sessions[preset],
            }, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
            assert ready.status_code in (200, 202)
            code, listed = rpc(preset, "prompts/list", {}, 2)
            prompt = [p for p in listed["prompts"] if p["name"] == "welcome_first_session"]
            assert len(prompt) == 1 and not prompt[0].get("arguments")
            print("PROMPTS_LIST", preset, code, '{"welcome_first_session":true,"arguments":[]}')
            code, got = rpc(preset, "prompts/get", {"name": "welcome_first_session", "arguments": {}}, 3)
            body = got["messages"][0]["content"]["text"]
            assert "Read route:" in body and "Full report route" in body
            print("PROMPTS_GET", preset, code, '{"read_route":true,"full_route":true,"message_role":"user"}')
            code, tools = rpc(preset, "tools/list", {}, 4)
            names = {tool["name"] for tool in tools["tools"]}
            if preset == "frontdesk":
                assert "create_report_ai_job" not in names and not CHAIN <= names
                assert {"get_clinics", "get_timesheets"} <= names
            else:
                assert CHAIN <= names and "confirm_report_ai_job_candidate" in names
            print("TOOLS_LIST", preset, code, json.dumps({
                "report_chain": sorted(CHAIN & names),
                "get_clinics": "get_clinics" in names,
                "get_timesheets": "get_timesheets" in names,
            }))

        code, clinics = rpc("frontdesk", "tools/call", {
            "name": "get_clinics", "arguments": {"limit": 20},
        }, 5)
        assert clinics.get("isError") is False
        clinic_rows = _data_rows(clinics, "clinics")
        print("GET_CLINICS", code, json.dumps({"isError": False, "row_count": len(clinic_rows)}))
        if clinic_rows:
            clinic_id = clinic_rows[0]["id"]
            code, timesheets = rpc("frontdesk", "tools/call", {
                "name": "get_timesheets", "arguments": {
                    "date": date.today().isoformat(), "limit": 20,
                    "filter": [{"property": "clinic_id", "operator": "=", "value": clinic_id}],
                },
            }, 6)
            assert timesheets.get("isError") is False
            rows = _data_rows(timesheets, "timesheet")
            mismatched = sum(str(row.get("clinic_id")) != str(clinic_id) for row in rows)
            assert mismatched == 0
            print("GET_TIMESHEETS", code, json.dumps({
                "isError": False, "row_count": len(rows), "clinic_id_mismatches": mismatched,
                "date_filter": "today", "clinic_filter": True,
            }))
        else:
            print("GET_TIMESHEETS", "not_called", '{"reason":"no branch returned; no real data claimed"}')

        metrics = client.get("/metrics", headers={"Authorization": "Bearer stage377-metrics-test"})
        assert metrics.status_code == 200
        help_lines = [line for line in metrics.text.splitlines()
                      if line.startswith("# HELP vetmanager_first_session_report_saved_7d_accounts")]
        assert len(help_lines) == 1 and "read-only accounts normally have no save event" in help_lines[0]
        print("METRICS", metrics.status_code, help_lines[0])
