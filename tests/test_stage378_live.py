"""Opt-in devtr6 HTTP evidence for the report_problem source contract."""

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
def test_report_problem_source_live_devtr6(live_server_url, prepared_web_db, monkeypatch):
    assert os.environ.get("TEST_DOMAIN") == "devtr6"
    assert os.environ["DATABASE_URL"] == f"sqlite:///{prepared_web_db}"
    assert "pytest" in str(prepared_web_db)
    monkeypatch.setenv("FEEDBACK_FINGERPRINT_PEPPER", "stage378-live-pepper")

    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage378-live@example.test", "password": "Stage378-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 378 devtr6", "expires_in_days": "1", "ip_mask": "*.*.*.*",
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

        code, _, headers = call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "stage378-source-check", "version": "1"},
        }, 1)
        assert code == 200
        if headers.get("mcp-session-id"):
            client.headers["Mcp-Session-Id"] = headers["mcp-session-id"]
        notified = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert notified.status_code in (200, 202)

        code, listed, _ = call("tools/list", {}, 2)
        description = next(tool["description"] for tool in listed["tools"] if tool["name"] == "report_problem")
        source_fragment = re.search(r"Source values:.*?person\.", description)
        assert source_fragment is not None and "auto" not in source_fragment.group()
        assert description.endswith("неверное описание.")
        print("TOOLS_LIST", code, json.dumps({"description": source_fragment.group()}, ensure_ascii=False))

        for number, source in enumerate(("system", "model", "human", "agent"), 3):
            code, result, _ = call("tools/call", {
                "name": "report_problem", "arguments": {
                    "category": "bug", "severity": "medium",
                    "summary": "Tool response is incomplete",
                    "details": "A required field is absent", "source": source,
                },
            }, number)
            if source == "system":
                assert result["isError"] is True
                message = result["content"][0]["text"]
                assert "model" in message and "human" in message
                print("TOOLS_CALL", source, code, json.dumps({"isError": True, "body": message}, ensure_ascii=False))
                continue
            content = result.get("structuredContent")
            if content is None:
                content = json.loads(result["content"][0]["text"])
            assert result["isError"] is False and content["ok"] is True
            feedback_id = content["feedback_id"]
            with sqlite3.connect(prepared_web_db) as db:
                row = db.execute("SELECT source FROM agent_feedback_reports WHERE id = ?", (feedback_id,)).fetchone()
            expected = "model" if source == "agent" else source
            assert row == (expected,)
            safe_body = {
                key: "<redacted>" if key.endswith("_id") else value
                for key, value in content.items()
            }
            print("TOOLS_CALL", source, code, json.dumps({
                "isError": False, "body": safe_body,
                "stored_source": row[0],
            }, ensure_ascii=False))

    prepared_web_db.unlink()
    assert not prepared_web_db.exists()
