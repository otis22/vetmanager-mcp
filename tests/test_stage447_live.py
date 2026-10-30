"""Published file-link guidance via local HTTP MCP on devtr6-configured stand."""

import os

import httpx
import pytest

from tests.test_stage380_live import _rpc
from tests.test_stage384_live import seed_devtr6_bearer

pytestmark = pytest.mark.real_api


@pytest.mark.skipif(os.environ.get("TEST_DOMAIN") != "devtr6" or not os.environ.get("TEST_API_KEY"),
                    reason="devtr6 contour absent")
def test_stage447_tools_list_publishes_safe_s3_guidance(live_server_url, prepared_web_db):
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    headers = {"Authorization": f"Bearer {token}",
               "Accept": "application/json, text/event-stream",
               "Content-Type": "application/json",
               "MCP-Protocol-Version": "2025-03-26"}
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=30) as client:
        init = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1,
            "method": "initialize", "params": {"protocolVersion": "2025-03-26",
            "capabilities": {}, "clientInfo": {"name": "stage447-live", "version": "1"}}})
        assert init.status_code == 200
        client.headers["Mcp-Session-Id"] = init.headers["mcp-session-id"]
        assert client.post("/mcp", json={"jsonrpc": "2.0",
            "method": "notifications/initialized"}).status_code in (200, 202)
        listed = client.post("/mcp", json={"jsonrpc": "2.0", "id": 2,
            "method": "tools/list", "params": {}})
    assert listed.status_code == 200
    tools = {tool["name"]: tool["description"] for tool in _rpc(listed)["result"]["tools"]}
    names = ("get_medical_cards", "get_medical_cards_by_date",
             "get_medical_cards_by_client_id", "get_medical_card_by_id", "get_pet_profile")
    for name in names:
        assert "publicly accessible S3 link" in tools[name]
        assert "closed or expired link" in tools[name]
    print("STAGE447_LIVE http=200 body=" + str({"tools_checked": len(names),
          "conditional_s3": True, "private_url_warning": True}))
