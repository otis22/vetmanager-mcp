"""Two real MCP bearer calls on the .env test contour; output has no secrets."""

import json
import os
import re

import httpx
import pytest

from access_summary import summarize_access
from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage388_live import _rpc
from tool_access_registry import TOKEN_PRESET_LABELS, TOKEN_PRESET_SCOPES


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="Requires the .env TEST_DOMAIN/TEST_API_KEY contour")
def test_stage397_whoami_two_token_groups_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage397-live@example.test", "password": "Stage397-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200

        for preset in ("read_only", "frontdesk"):
            issued = _post_with_csrf_sync(client, "/account/tokens", data={
                "token_name": f"Stage 397 {preset}", "expires_in_days": "1",
                "ip_mask": "*.*.*.*", "access_preset": preset,
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
            client.headers.pop("Mcp-Session-Id", None)
            initialized = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "stage397-live", "version": "1"},
                },
            })
            assert initialized.status_code == 200
            client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
            assert client.post("/mcp", json={
                "jsonrpc": "2.0", "method": "notifications/initialized",
            }).status_code in (200, 202)
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "whoami", "arguments": {}},
            })
            assert response.status_code == 200
            result = _rpc(response)["result"]
            assert result.get("isError") is not True
            body = result.get("structuredContent") or json.loads(result["content"][0]["text"])
            assert body["clinic_domain"] == os.environ["TEST_DOMAIN"]
            assert body["groups"] == [TOKEN_PRESET_LABELS[preset]]
            assert body["scopes"] == list(TOKEN_PRESET_SCOPES[preset])
            assert body["access_summary"] == dict(summarize_access(body["scopes"]))
            assert body["limits"]["requests"] > 0
            assert body["limits"]["window_seconds"] > 0
            print("WHOAMI", response.status_code, json.dumps({
                "preset": preset, "domain_present": bool(body["clinic_domain"]),
                "groups": body["groups"], "scope_count": len(body["scopes"]),
                "summary_keys": list(body["access_summary"]),
                "deletion": body["access_summary"]["Удаление"],
                "limit_fields": sorted(body["limits"]),
            }, ensure_ascii=False))
