"""Opt-in devtr6 MCP HTTP prompt smoke; no Report AI tools are called."""

import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


def _rpc(response: httpx.Response) -> dict:
    if "text/event-stream" in response.headers.get("content-type", ""):
        events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        assert events
        return json.loads(events[-1])
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 API key absent")
def test_welcome_prompt_live_http_on_devtr6(live_server_url):
    assert os.environ.get("TEST_DOMAIN") == "devtr6"
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage375-live@example.test", "password": "Stage375-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 375 devtr6 prompt smoke", "expires_in_days": "1", "ip_mask": "*.*.*.*",
        }, page_path="/account")
        assert issued.status_code == 200
        token = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert token is not None
        client.headers.update({
            "Authorization": f"Bearer {token.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        })

        def call(method: str, params: dict, request_id: int) -> tuple[int, dict, httpx.Headers]:
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": method, "params": params,
            })
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            return response.status_code, body["result"], response.headers

        init_code, initialized, init_headers = call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "stage375-prompt-smoke", "version": "1"},
        }, 1)
        assert "welcome_first_session" in initialized["instructions"]
        print("INITIALIZE", init_code, json.dumps({"instructions": initialized["instructions"]}, ensure_ascii=False))
        # Streamable HTTP sessions may be stateful depending on server configuration.
        session_id = init_headers.get("mcp-session-id")
        if session_id:
            client.headers["Mcp-Session-Id"] = session_id
        notified = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert notified.status_code in (200, 202)
        listed_code, listed, _ = call("prompts/list", {}, 2)
        prompts = [p for p in listed["prompts"] if p["name"] == "welcome_first_session"]
        assert len(prompts) == 1 and not prompts[0].get("arguments")
        print("PROMPTS_LIST", listed_code, json.dumps({"prompts": prompts}, ensure_ascii=False))
        got_code, got, _ = call("prompts/get", {"name": "welcome_first_session", "arguments": {}}, 3)
        assert len(got["messages"]) == 1 and got["messages"][0]["role"] == "user"
        assert "get_report_ai_job_data" in got["messages"][0]["content"]["text"]
        print("PROMPTS_GET", got_code, json.dumps({"isError": False, "messages": got["messages"]}, ensure_ascii=False))
