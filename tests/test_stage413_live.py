"""Live HTTP MCP prompt text on the isolated .env test contour."""

import json
import os

import httpx
import pytest

from tests.test_stage384_live import seed_devtr6_bearer


@pytest.mark.real_api
@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 credentials absent")
def test_stage413_report_ai_prompt_live(live_server_url, prepared_web_db, upstream_mock_router):
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
                "clientInfo": {"name": "stage413-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        assert client.post("/mcp", json={
            "jsonrpc": "2.0", "method": "notifications/initialized",
        }).status_code in (200, 202)
        response = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 2, "method": "prompts/get", "params": {
                "name": "report_ai_prompt_helper", "arguments": {},
            },
        })
        assert response.status_code == 200
        if "text/event-stream" in response.headers.get("content-type", ""):
            body = next(json.loads(line[6:]) for line in response.text.splitlines()
                        if line.startswith("data: "))
        else:
            body = response.json()
        text = body["result"]["messages"][0]["content"]["text"]
        assert text.startswith("# Report AI prompt helper")
        assert text.index("## Короткий маршрут") < text.index("## Приложение: доступ и плейсхолдеры")
        assert "[client:123:last_name]" in text
        print("stage413 MCP prompts/get HTTP 200 body="
              + repr(text[:210]) + " ... "
              + repr(text[text.index("## Приложение: доступ и плейсхолдеры"):][:240]))
