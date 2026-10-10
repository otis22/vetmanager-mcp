"""Opt-in devtr6 HTTP evidence for prompt and expiry metrics; output is redacted."""

import asyncio
import json
import os
import re

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync

pytestmark = pytest.mark.real_api


def _rpc(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        return json.loads([line[6:] for line in response.text.splitlines() if line.startswith("data: ")][-1])
    return response.json()


@pytest.mark.skipif(not os.environ.get("TEST_API_KEY"), reason="devtr6 API key absent")
def test_stage379_live_devtr6(live_server_url, browser_account_cleanup, monkeypatch):
    assert os.environ.get("TEST_DOMAIN") == "devtr6"
    browser_account_cleanup.track_account_email("stage379-live@example.test")
    metrics_token = os.environ.get("METRICS_AUTH_TOKEN")
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        def metrics():
            headers = {"Authorization": f"Bearer {metrics_token}"} if metrics_token else {}
            response = client.get("/metrics", headers=headers)
            assert response.status_code == 200
            return response.text

        before = metrics()
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage379-live@example.test", "password": "Stage379-live-pass-123",
        })
        integrated = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 379 devtr6 expiry smoke", "expires_in_days": "1", "ip_mask": "*.*.*.*",
        }, page_path="/account")
        assert (registered.status_code, integrated.status_code, issued.status_code) == (200, 200, 200)
        token = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert token is not None
        client.headers.update({
            "Authorization": f"Bearer {token.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        })

        def call(method, params, number):
            response = client.post("/mcp", json={"jsonrpc": "2.0", "id": number, "method": method, "params": params})
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            return response, body["result"]

        initialized, init = call("initialize", {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "stage379-smoke", "version": "1"},
        }, 1)
        if initialized.headers.get("mcp-session-id"):
            client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        listed, catalogue = call("prompts/list", {}, 2)
        got, prompt = call("prompts/get", {"name": "welcome_first_session", "arguments": {}}, 3)
        private_argument = "private-query-79991234567"
        queried, queried_prompt = call("prompts/get", {"name": "find_client", "arguments": {"query": private_argument}}, 31)
        assert "welcome_first_session" in init["instructions"]
        assert len(catalogue["prompts"]) == 21
        assert len(prompt["messages"]) == 1 and prompt["messages"][0]["role"] == "user"
        assert queried.status_code == 200 and len(queried_prompt["messages"]) == 1
        after_prompts = metrics()
        assert 'vetmanager_prompt_requests_total{method="list",prompt="welcome_first_session"} 1' in after_prompts
        assert 'vetmanager_prompt_requests_total{method="get",prompt="welcome_first_session"} 1' in after_prompts
        assert 'vetmanager_prompt_requests_total{method="get",prompt="find_client"} 1' in after_prompts
        assert private_argument not in after_prompts

        first, first_result = call("tools/call", {"name": "get_clients", "arguments": {"limit": 1}}, 4)
        second, second_result = call("tools/call", {"name": "get_clients", "arguments": {"limit": 1}}, 5)
        def notice(result):
            return [part for part in result["content"] if part.get("type") == "text" and part.get("text", "").startswith("Токен истекает через")]
        assert not first_result.get("isError", False) and len(notice(first_result)) == 1
        assert not second_result.get("isError", False) and not notice(second_result)
        after_calls = metrics()
        assert 'vetmanager_token_expiry_notice_issued_total{threshold="1d",outcome="appended"} 1' in after_calls
        assert 'vetmanager_token_expiry_notice_skipped_total{outcome="claim_recent"} 1' in after_calls

        import token_expiry_notice
        async def delayed_claim(*args, **kwargs):
            async with asyncio.timeout(0.5):
                await asyncio.sleep(0.6)
        monkeypatch.setattr(token_expiry_notice, "claim_expiry_notice", delayed_claim)
        delayed, delayed_result = call("tools/call", {"name": "get_clients", "arguments": {"limit": 1}}, 6)
        assert not delayed_result.get("isError", False) and not notice(delayed_result)
        after_delay = metrics()
        assert 'vetmanager_token_expiry_notice_skipped_total{outcome="deadline"} 1' in after_delay
        selected = [line for line in after_delay.splitlines() if line.startswith((
            "# HELP vetmanager_prompt_requests_total", "# TYPE vetmanager_prompt_requests_total",
            "# HELP vetmanager_token_expiry_notice_", "# TYPE vetmanager_token_expiry_notice_",
            'vetmanager_prompt_requests_total{method="get",prompt="welcome_first_session"}',
            'vetmanager_prompt_requests_total{method="list",prompt="welcome_first_session"}',
            "vetmanager_token_expiry_notice_issued_total{", "vetmanager_token_expiry_notice_skipped_total{",
        ))]
        assert all("vm_st_" not in line and "stage379-live" not in line for line in selected)
        print("STAGE379_LIVE", {"register": registered.status_code, "integration": integrated.status_code,
                                 "issue": issued.status_code, "initialize": initialized.status_code,
                                 "initialized": ready.status_code, "list": listed.status_code,
                                 "get": got.status_code, "get_with_argument": queried.status_code,
                                 "tool_first": first.status_code,
                                 "tool_second": second.status_code, "tool_deadline": delayed.status_code,
                                 "metrics": 200, "before_new_series": sum("vetmanager_prompt_requests_total{" in x for x in before.splitlines()),
                                 "catalogue_count": len(catalogue["prompts"]), "prompt_role": prompt["messages"][0]["role"],
                                 "first_notice": len(notice(first_result)), "second_notice": len(notice(second_result)),
                                 "deadline_notice": len(notice(delayed_result))})
        print("STAGE379_METRICS", selected)
