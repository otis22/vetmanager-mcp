"""Stage 417: live HTTP MCP descriptions and prompt helper on local server."""

import json
import os

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


def _rpc(response):
    assert response.status_code == 200
    if "text/event-stream" in response.headers.get("content-type", ""):
        return next(json.loads(line[6:]) for line in response.text.splitlines()
                    if line.startswith("data: "))
    return response.json()


@pytest.mark.real_api
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour credentials absent")
def test_stage417_live_descriptions_and_helper(live_server_url, prepared_web_db):
    assert "pytest" in str(prepared_web_db)
    token = seed_devtr6_bearer()
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
                "clientInfo": {"name": "stage417-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }).status_code in (200, 202)
        listed = _rpc(client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        }))
        tools = {tool["name"]: tool["description"] for tool in listed["result"]["tools"]}
        for name in ("create_report_ai_job", "get_report_ai_job",
                     "get_report_ai_job_data", "rate_report_ai_job"):
            description = tools[name]
            assert "placeholders" in description or "плейсхолдерами" in description
            assert "personal-data token" in description or "токене с ПД" in description
            assert "does not guarantee redaction of every report" in description or "не гарантия очистки каждого отчёта" in description
            assert "when the task is solved" in description or "если задача решена" in description
            marker = "Report AI prefers" if name != "rate_report_ai_job" else "Report AI может"
            print(f"STAGE417 tools/list HTTP 200 {name}: "
                  + repr(description[description.index(marker):][:390]))

        prompted = _rpc(client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 3, "method": "prompts/get", "params": {
                "name": "report_ai_prompt_helper", "arguments": {},
            },
        }))
        helper = prompted["result"]["messages"][0]["content"]["text"]
        assert "даже при токене с ПД" in helper
        assert "не снижайте оценку только" in helper
        assert "не гарантия очистки каждого отчёта" in helper
        assert "если задача решена" in " ".join(helper.split())
        print("STAGE417 prompts/get HTTP 200: "
              + repr(helper[helper.index("Report AI предпочитает"):][:390]))

        called = _rpc(client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {
                "name": "get_report_ai_prompt_helper", "arguments": {},
            },
        }))
        tool_helper = called["result"]["structuredContent"]["helper_text"]
        assert tool_helper == helper
        print("STAGE417 tools/call get_report_ai_prompt_helper HTTP 200: "
              + repr(tool_helper[tool_helper.index("Report AI предпочитает"):][:390]))
