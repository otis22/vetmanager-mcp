"""Opt-in bearer MCP and real devtr6 proof for JSON-encoded filters."""

import json
import os

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


@pytest.mark.real_api
@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_stage430_bearer_json_filter_live(live_server_url):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    token = seed_devtr6_bearer()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }

    def payload(response):
        if "text/event-stream" in response.headers.get("content-type", ""):
            return next(json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: "))
        return response.json()

    with httpx.Client(base_url=live_server_url, timeout=60, headers=headers) as client:
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage430-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }).status_code in (200, 202)

        def call(filter_value, request_id):
            args = {"limit": 2, "status": ""}
            if filter_value is not None:
                args["filter"] = filter_value
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": "get_clients", "arguments": args},
            })
            assert response.status_code == 200
            result = payload(response)["result"]
            assert not result.get("isError")
            return response.status_code, result["structuredContent"]

        clause = [{"property": "id", "value": 0, "operator": "="}]
        status, encoded = call(json.dumps(clause), 2)
        _, native = call(clause, 3)
        _, unfiltered = call(None, 4)
        assert encoded == native
        assert encoded["data"] == {"totalCount": 0, "client": []}
        assert unfiltered["data"]["totalCount"] > 0
        print("STAGE430_LIVE", json.dumps({"code": status, "body": encoded}, ensure_ascii=False))
