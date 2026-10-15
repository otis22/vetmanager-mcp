"""Read-only projection proof on the opt-in .env test API contour."""

import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage388_live import _rpc


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason="test API credentials absent")
def test_stage399_projection_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage399-live@example.test", "password": "Stage399-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 399 projection read", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "full_access",
            "confirm_full_access": "1",
        }, page_path="/account")
        assert issued.status_code == 200
        match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert match is not None
        client.headers.update({
            "Authorization": f"Bearer {match.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json", "MCP-Protocol-Version": "2025-03-26",
        })
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage399-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)

        request_id = 2
        for tool, entity in (("get_admissions", "admission"),
                             ("get_invoices", "invoice"), ("get_clients", "client")):
            sizes = {}
            for mode, arguments in (("full", {"limit": 1}),
                                    ("fields", {"limit": 1, "fields": ["id", "status"]}),
                                    ("compact", {"limit": 1, "compact": True})):
                response = client.post("/mcp", json={
                    "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments},
                })
                request_id += 1
                assert response.status_code == 200
                result = _rpc(response)["result"]
                assert not result.get("isError"), f"{tool}/{mode} returned an error"
                payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
                assert payload.get("success") is True
                data = payload["data"]
                rows = data if isinstance(data, list) else data[entity]
                assert rows and isinstance(rows[0], dict), f"{tool}/{mode} needs a nonempty list"
                if mode == "fields":
                    assert set(rows[0]) == {"id", "status"}
                encoded_bytes = len(json.dumps(payload, ensure_ascii=False).encode())
                sizes[mode] = encoded_bytes
                safe_body = {
                    "success": True, "row_count": len(rows),
                    "total_present": isinstance(data, dict) and "totalCount" in data,
                    "row_key_count": len(rows[0]), "bytes": encoded_bytes,
                }
                print("STAGE399_LIVE", tool, mode, response.status_code,
                      json.dumps(safe_body, sort_keys=True))
            assert sizes["compact"] < sizes["full"], tool
