"""Read-only MCP proof on the .env test API contour, with safe output."""

import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync
from tests.test_stage388_live import _rpc, _rows


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"), reason="test API credentials absent")
def test_stage390_free_slots_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage390-live@example.test", "password": "Stage390-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 390 schedule read", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "frontdesk",
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
                "clientInfo": {"name": "stage390-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code in (200, 202)

        def call(name, args, request_id):
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": name, "arguments": args},
            })
            assert response.status_code == 200
            result = _rpc(response)["result"]
            return response.status_code, result

        _, timesheets = call("get_timesheets", {"limit": 20}, 2)
        rows = _rows(timesheets)
        assert rows, "test contour needs one timesheet row"
        row = next((item for item in rows if int(item.get("doctor_id") or 0) > 0), None)
        assert row is not None
        day = row["begin_datetime"][:10]
        args = {"doctor_id": int(row["doctor_id"]), "date_from": day, "date_to": day}
        code, result = call("get_doctor_free_slots", args, 3)
        payload = result.get("structuredContent") or {}
        if result.get("isError"):
            message = result.get("content", [{}])[0].get("text", "")
            assert "timesheet_types" in message and "work_title" in message
            shape = {"isError": True, "names_type_and_remedy": True}
        else:
            assert payload.get("success") is True
            shape = {"isError": False, "total_slots": payload["total_slots"],
                     "warning_present": bool(payload.get("warning"))}
        print("GET_DOCTOR_FREE_SLOTS", code, json.dumps(shape))

        fallback_code, fallback = call("get_doctor_free_slots", {
            **args, "work_title": row.get("title") or "Рабочее время",
        }, 4)
        fallback_payload = fallback.get("structuredContent") or {}
        if fallback.get("isError"):
            fallback_message = fallback.get("content", [{}])[0].get("text", "")
            assert "timesheet_types" in fallback_message and "work_title" in fallback_message
            fallback_shape = {"isError": True, "names_type_and_remedy": True}
        else:
            assert fallback_payload.get("success") is True
            if result.get("isError"):
                assert "завыш" in fallback_payload.get("warning", "")
            fallback_shape = {"isError": False,
                              "total_slots": fallback_payload["total_slots"],
                              "warning_present": bool(fallback_payload.get("warning"))}
        print("GET_DOCTOR_FREE_SLOTS_FALLBACK", fallback_code, json.dumps({
            **fallback_shape,
        }))
