"""Read-only devtr6 MCP calls for the two timeout-budget consumers."""

import os
import time

import httpx
import pytest

from tests.test_stage380_live import _rpc
from tests.test_stage384_live import seed_devtr6_bearer


pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 key absent")
def test_stage403_live_read_tools(live_server_url, prepared_web_db):
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
        initialized = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-03-26",
                "capabilities": {}, "clientInfo": {"name": "stage403-live", "version": "1"}}})
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0",
            "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)

        for number, name, arguments in (
            (2, "get_medical_cards_by_date", {"date": "2026-10-22", "limit": 1}),
            (3, "get_invoices", {"limit": 1}),
        ):
            started = time.monotonic()
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": number,
                "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            elapsed = round(time.monotonic() - started, 3)
            assert response.status_code == 200
            result = _rpc(response)["result"]
            assert result.get("isError") is not True
            body = result.get("structuredContent") or {}
            assert body.get("success") is True
            safe_body = {"success": body.get("success"),
                         "has_data": isinstance(body.get("data"), dict),
                         "has_medical_cards": isinstance(body.get("medical_cards"), list),
                         "medical_cards_count": body.get("medical_cards_count")}
            print("STAGE403_LIVE", {"tool": name, "http_code": response.status_code,
                                    "body": safe_body, "elapsed_s": elapsed})
