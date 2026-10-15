"""Read-only two-page HTTP MCP proof on the separate .env test API contour."""

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
        return json.loads(events[-1])
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"), reason="test API credentials absent")
def test_stage389_two_live_pages(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage389-live@example.test", "password": "Stage389-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 389 inactive pet read", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "read_only",
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
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage389-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)

        def call(args, request_id):
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": "get_inactive_pets", "arguments": args},
            })
            assert response.status_code == 200
            result = _rpc(response)["result"]
            assert result.get("isError") is False
            data = result.get("structuredContent")
            if data is None:
                data = json.loads(result["content"][0]["text"])
            return response.status_code, data

        args = {"months_min": 1, "months_max": 240, "limit": 1}
        first_code, first = call(args, 2)
        assert len(first["inactive_pets"]) == 1, "test contour needs two qualifying pets"
        assert first["has_more"] is True and first["next_cursor"]
        second_code, second = call({**args, "cursor": first["next_cursor"]}, 3)
        first_ids = {p["id"] for p in first["inactive_pets"]}
        second_ids = {p["id"] for p in second["inactive_pets"]}
        assert second_ids and first_ids.isdisjoint(second_ids)
        print("GET_INACTIVE_PETS_PAGES", json.dumps({
            "codes": [first_code, second_code],
            "counts": [len(first_ids), len(second_ids)],
            "overlap_count": len(first_ids & second_ids),
            "has_more": [first["has_more"], second["has_more"]],
            "second_cursor_present": bool(second["next_cursor"]),
        }))
