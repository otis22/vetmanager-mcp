"""Opt-in bearer HTTP proof of the published stage 411 catalog and Good route."""

import os

import httpx
import pytest

from tests.test_stage380_live import _rpc
from tests.test_stage384_live import seed_devtr6_bearer


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_stage411_bearer_tools_list_and_goods_title(live_server_url, prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=45) as client:
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage411-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200, initialized.text[:200]
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        assert listed.status_code == 200, listed.text[:200]
        tools = {tool["name"]: tool for tool in _rpc(listed)["result"]["tools"]}
        assert "name" not in tools["get_goods"]["inputSchema"]["properties"]
        assert "title" in tools["get_goods"]["inputSchema"]["properties"]
        assert "client_id" not in tools["get_payments"]["inputSchema"]["properties"]
        assert "is_working_hours" in tools["get_timesheet_types"]["description"]
        assert "get_doctor_free_slots" in tools["get_timesheet_types"]["description"]
        assert "get_medical_cards_by_client_id" in tools["get_medical_cards"]["description"]
        assert "get_medical_cards_by_date" in tools["get_medical_cards"]["description"]
        assert "pet_id" in tools["get_medical_cards"]["inputSchema"]["required"]
        assert "payment_status can be stale" in tools["get_invoices"]["description"]
        print("STAGE411_TOOLS_LIST", {"http_code": listed.status_code,
              "goods_has_title": True, "goods_has_name": False,
              "payments_has_client_id": False,
              "timesheet_hint": "is_working_hours / get_doctor_free_slots",
              "cards_hint": "by_client_id / by_date", "invoice_hint": "payment_status can be stale"})

        def get_goods(request_id, arguments):
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id,
                "method": "tools/call", "params": {"name": "get_goods", "arguments": arguments}})
            assert response.status_code == 200, response.text[:200]
            result = _rpc(response)["result"]
            assert not result.get("isError"), str(result.get("content"))[:200]
            body = result.get("structuredContent") or {}
            assert body.get("success") is True, str(body.get("message"))[:200]
            data = body.get("data")
            rows = data if isinstance(data, list) else next(
                (value for value in data.values() if isinstance(value, list)), []
            ) if isinstance(data, dict) else []
            return response.status_code, body, rows

        _, _, baseline = get_goods(3, {"limit": 20})
        title = next((row.get("title") for row in baseline
                      if isinstance(row, dict) and isinstance(row.get("title"), str)
                      and len(row["title"].strip()) >= 3), None)
        assert title, "Live catalog has no searchable title"
        fragment = title.strip()[:3]
        code, body, matches = get_goods(4, {"title": f"%{fragment}%", "limit": 20})
        assert matches, "Live title search returned no rows"
        assert all(fragment.casefold() in row.get("title", "").casefold()
                   for row in matches if isinstance(row, dict))
        print("STAGE411_GET_GOODS", {"http_code": code,
              "body_keys": sorted(body)[:8], "isError": False,
              "title_fragment_matched": True})
