"""Opt-in live MCP HTTP proof for stage 412 on the devtr6 test contour."""

import os

import httpx
import pytest

from tests.test_stage380_live import _rpc
from tests.test_stage384_live import seed_devtr6_bearer

pytestmark = pytest.mark.real_api


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="test credentials absent")
def test_stage412_live_stock_batch_and_missing_clinic(live_server_url, prepared_web_db):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=90) as client:
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage412-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)

        def call(request_id, name, arguments):
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id,
                "method": "tools/call", "params": {"name": name, "arguments": arguments}})
            return response.status_code, _rpc(response)

        code, payload = call(2, "get_goods_stock_balances",
                             {"good_ids": [470, 192], "clinic_id": 1})
        assert code == 200, str(payload)[:300]
        result = payload["result"]
        assert result.get("isError") is not True, str(result)[:400]
        body = result.get("structuredContent") or {}
        assert body["clinic_id"] == 1
        assert [row["good_id"] for row in body["balances"]] == [470, 192]
        assert all(isinstance(row["quantity"], (int, float)) for row in body["balances"])
        print("STAGE412_BATCH", {"http_code": code, "body": body})

        for request_id, name, args in (
            (3, "get_good_stock_balance", {"good_id": 470}),
            (4, "get_goods_stock_balances", {"good_ids": [470, 192]}),
        ):
            code, payload = call(request_id, name, args)
            assert code == 200, str(payload)[:300]
            result = payload["result"]
            assert result.get("isError") is True, str(result)[:300]
            assert "clinic_id" in str(result.get("content")), str(result)[:300]
            print("STAGE412_MISSING_CLINIC", {"tool": name, "http_code": code,
                  "body": {"isError": True, "content": result.get("content")}})
