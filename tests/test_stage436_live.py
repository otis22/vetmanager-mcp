"""Opt-in devtr6 HTTP MCP evidence for invalid and valid feedback calls."""

import json
import os
import re
import sqlite3

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


def _rpc(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        assert events
        return json.loads(events[-1])
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 API key absent")
def test_report_problem_validation_live_devtr6(live_server_url, prepared_web_db, monkeypatch):
    assert os.environ.get("TEST_DOMAIN") == "devtr6"
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage436-live-pepper")

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage436-live@example.test", "password": "Stage436-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 436 devtr6", "expires_in_days": "1", "ip_mask": "*.*.*.*",
        }, page_path="/account")
        assert issued.status_code == 200
        token = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert token is not None
        client.headers.update({
            "Authorization": f"Bearer {token.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        })

        def call(method, params, number):
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": number, "method": method, "params": params,
            })
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            return response.status_code, body["result"], response.headers

        _, _, headers = call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "stage436-validation-check", "version": "1"},
        }, 1)
        if headers.get("mcp-session-id"):
            client.headers["Mcp-Session-Id"] = headers["mcp-session-id"]
        notified = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert notified.status_code in (200, 202)

        code, bad, _ = call("tools/call", {"name": "report_problem", "arguments": {
            "category": "bug", "severity": "medium", "summary": "Safe validation test",
        }}, 2)
        message = bad["content"][0]["text"]
        assert bad["isError"] is True
        assert "details" in message and 'details="Safe description without personal data"' in message
        print("TOOLS_CALL_INVALID", code, json.dumps({"isError": True, "body": message}))

        code, good, _ = call("tools/call", {"name": "report_problem", "arguments": {
            "category": "bug", "severity": "medium", "summary": "Safe validation test",
            "details": "Stage 436 live validation check without personal data",
        }}, 3)
        content = good.get("structuredContent") or json.loads(good["content"][0]["text"])
        assert good["isError"] is False and content["ok"] is True
        with sqlite3.connect(prepared_web_db) as db:
            row = db.execute(
                "SELECT summary FROM agent_feedback_reports WHERE id = ?", (content["feedback_id"],)
            ).fetchone()
            total = db.execute("SELECT COUNT(*) FROM agent_feedback_reports").fetchone()[0]
        assert row == ("Safe validation test",)
        assert total == 1
        print("TOOLS_CALL_VALID", code, json.dumps({
            "isError": False, "body": {"ok": content["ok"], "feedback_id": "<redacted>"},
            "stored_summary": row[0], "stored_count": total,
        }))

    prepared_web_db.unlink()
