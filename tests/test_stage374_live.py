"""Opt-in devtr6 first-session smoke with redacted evidence only."""

import json
import os
import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import create_engine, text

from storage import normalize_database_url_for_migrations

from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


def _rpc(response: httpx.Response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        payloads = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        assert payloads
        return json.loads(payloads[-1])
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_first_session_live_devtr6(live_server_url, monkeypatch):
    monkeypatch.setenv("FIRST_SESSION_RELEASE_CUTOFF_UTC", (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())
    monkeypatch.setenv("METRICS_AUTH_TOKEN", "stage374-metrics-test")
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage374-live@example.test", "password": "Stage374-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 374 devtr6 read smoke", "expires_in_days": "1", "ip_mask": "*.*.*.*",
        }, page_path="/account")
        assert issued.status_code == 200
        match = re.search(r"vm_st_[A-Za-z0-9_\-]+", issued.text)
        assert match is not None
        print('CREDENTIAL', issued.status_code, '{"one_time_token":"<redacted>","issued":true}')
        headers = {
            "Authorization": f"Bearer {match.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        }
        initialized = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage374-smoke", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        body = _rpc(initialized)
        instructions = body["result"]["instructions"]
        assert "welcome_first_session" in instructions
        assert "tools/list before any write" in instructions
        assert "safe read route" in instructions
        print("INITIALIZE", initialized.status_code, '{"welcome_pointer":true,"read_route":true}')
        engine = create_engine(normalize_database_url_for_migrations(os.environ["DATABASE_URL"]))
        with engine.connect() as conn:
            anchored, tool_success = conn.execute(text(
                "SELECT count(*), count(first_tool_success_at) FROM account_first_sessions"
            )).one()
        assert anchored == 1 and tool_success == 0, "issuance and initialize are not data-tool success"
        session_id = initialized.headers.get("mcp-session-id")
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        ready = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)
        read = client.post("/mcp", headers=headers, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "get_timesheets", "arguments": {"date": datetime.now().date().isoformat(), "limit": 1}},
        })
        assert read.status_code == 200
        read_body = _rpc(read)
        assert not read_body.get("result", {}).get("isError", True)
        print("READ", read.status_code, '{"isError":false,"data":"<redacted>"}')
        with engine.connect() as conn:
            anchored, tool_success = conn.execute(text(
                "SELECT count(*), count(first_tool_success_at) FROM account_first_sessions"
            )).one()
        engine.dispose()
        assert anchored == 1 and tool_success == 1
        print("FIRST_SESSION_DB", json.dumps({"anchored_accounts": anchored, "tool_success_accounts": tool_success}))
        metrics = client.get("/metrics", headers={"Authorization": "Bearer stage374-metrics-test"})
        assert metrics.status_code == 200
        lines = [line for line in metrics.text.splitlines() if line.startswith("vetmanager_first_session_")]
        assert any(line.startswith("vetmanager_first_session_eligible_accounts ") for line in lines)
        print("METRICS", metrics.status_code, json.dumps(lines))
