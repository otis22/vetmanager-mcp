"""Opt-in HTTP tools/list proof for stage 387 on isolated devtr6."""

import json
import os

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


@pytest.mark.real_api
@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_stage387_live_texts(live_server_url, prepared_web_db, upstream_mock_router):
    assert os.environ["TEST_DOMAIN"] == "devtr6"
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
    upstream_mock_router.get("https://billing-api.vetmanager.cloud/host/devtr6").mock(
        return_value=httpx.Response(200, json={"data": {"url": "https://devtr6.vetmanager.cloud"}}))
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
        "MCP-Protocol-Version": "2025-03-26",
    }
    with httpx.Client(base_url=live_server_url, headers=headers, timeout=30) as client:
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage387-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }).status_code in (200, 202)
        response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        assert response.status_code == 200
        if "text/event-stream" in response.headers.get("content-type", ""):
            body = next(json.loads(line[6:]) for line in response.text.splitlines()
                        if line.startswith("data: "))
        else:
            body = response.json()
        tools = {tool["name"]: tool["description"] for tool in body["result"]["tools"]}
        assert "pet_id" in tools["get_medical_cards_by_client_id"]
        assert "get_medical_cards_by_client_id" in tools["get_medical_cards_by_date"]
        assert "paid_by_executed_invoices" in tools["get_debtors"]
        assert "get_report_export_download" in tools["get_report_ai_job_data"]
        helper_response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {
                "name": "get_report_ai_prompt_helper", "arguments": {},
            },
        })
        assert helper_response.status_code == 200
        if "text/event-stream" in helper_response.headers.get("content-type", ""):
            helper_body = next(json.loads(line[6:]) for line in helper_response.text.splitlines()
                               if line.startswith("data: "))
        else:
            helper_body = helper_response.json()
        assert helper_body["result"].get("isError") is not True
        helper_text = helper_body["result"]["structuredContent"]["helper_text"]
        assert "6–10 секунд" in helper_text
        assert "get_report_export_download" in helper_text
        print("stage387 live devtr6: tools/list HTTP 200 body=four corrected descriptions; "
              "get_report_ai_prompt_helper HTTP 200 body=current timing and export route")
