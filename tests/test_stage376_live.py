"""Opt-in devtr6 expiry notice smoke. Only sanitized response metadata is printed."""

import json
import os
import re

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
def test_expiry_notice_live_devtr6(live_server_url, browser_account_cleanup, monkeypatch):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    browser_account_cleanup.track_account_email("stage376-live@example.test")
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage376-live@example.test", "password": "Stage376-live-pass-123",
        })
        assert registered.status_code == 200
        integrated = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integrated.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 376 devtr6 expiry smoke", "expires_in_days": "1", "ip_mask": "*.*.*.*",
        }, page_path="/account")
        assert issued.status_code == 200
        match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert match is not None
        client.headers.update({
            "Authorization": f"Bearer {match.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        })

        def call(method, params, number):
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": number, "method": method, "params": params})
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            return response.status_code, body["result"], response.headers

        init_code, _, headers = call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "stage376-smoke", "version": "1"},
        }, 1)
        if headers.get("mcp-session-id"):
            client.headers["Mcp-Session-Id"] = headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)
        print("STAGE376_SETUP", {"register": registered.status_code, "integration": integrated.status_code,
                                  "issue": issued.status_code, "initialize": init_code, "initialized": ready.status_code})

        results = []
        for number, name in enumerate(("get_timesheets", "get_clients"), 2):
            code, result, _ = call("tools/call", {"name": name, "arguments": {"limit": 1}}, number)
            assert not result.get("isError", False)
            notices = [part["text"] for part in result["content"]
                       if part.get("type") == "text" and part.get("text", "").startswith("Токен истекает через")]
            results.append(notices)
            print("STAGE376_CALL", {"tool": name, "http": code, "isError": False,
                                     "warning": notices, "structured_keys": sorted(result.get("structuredContent", {})),
                                     "content_blocks": len(result["content"])})
        assert len(results[0]) == 1 and results[1] == []

        import tool_error_tracking

        async def fail_annotation(*args):
            raise RuntimeError("simulated annotation failure")

        monkeypatch.setattr(tool_error_tracking, "_add_expiry_notice", fail_annotation)
        fault_code, fault_result, _ = call("tools/call", {
            "name": "get_clients", "arguments": {"limit": 1},
        }, 4)
        assert not fault_result.get("isError", False)
        assert not any(part.get("text", "").startswith("Токен истекает через") for part in fault_result["content"])
        print("STAGE376_ANNOTATION_FAILURE", {"http": fault_code, "isError": False,
                                               "warning": [], "structured_keys": sorted(fault_result.get("structuredContent", {})),
                                               "content_blocks": len(fault_result["content"])})
