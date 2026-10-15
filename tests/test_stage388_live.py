"""Opt-in .env test API proof for timesheet range and newest-first order."""

import json
import os
import re
from datetime import date, timedelta

import httpx
import pytest

from tests.test_e2e_real import _post_with_csrf_sync


pytestmark = pytest.mark.real_api


def _rpc(response):
    if "text/event-stream" in response.headers.get("content-type", ""):
        events = [line[6:] for line in response.text.splitlines() if line.startswith("data: ")]
        return json.loads(events[-1])
    return response.json()


def _rows(result):
    payload = result.get("structuredContent")
    if payload is None:
        payload = json.loads(result["content"][0]["text"])
    data = payload.get("data", payload)
    if isinstance(data, dict):
        data = data["timesheet"]
    assert isinstance(data, list)
    return data


@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"), reason="test API credentials absent")
def test_stage388_timesheets_live(live_server_url):
    with httpx.Client(base_url=live_server_url, follow_redirects=True, timeout=60) as client:
        registered = _post_with_csrf_sync(client, "/register", data={
            "email": "stage388-live@example.test", "password": "Stage388-live-pass-123",
        })
        assert registered.status_code == 200
        integration = _post_with_csrf_sync(client, "/account/integration", data={
            "auth_mode": "domain_api_key", "domain": os.environ["TEST_DOMAIN"],
            "api_key": os.environ["TEST_API_KEY"],
        }, page_path="/account")
        assert integration.status_code == 200
        issued = _post_with_csrf_sync(client, "/account/tokens", data={
            "token_name": "Stage 388 timesheet read", "expires_in_days": "1",
            "ip_mask": "*.*.*.*", "access_preset": "frontdesk",
        }, page_path="/account")
        assert issued.status_code == 200
        match = re.search(r"vm_st_[A-Za-z0-9_-]+", issued.text)
        assert match is not None
        client.headers.update({
            "Authorization": f"Bearer {match.group(0)}",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": "2025-03-26",
        })
        initialized = client.post("/mcp", json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "stage388-live", "version": "1"},
            },
        })
        assert initialized.status_code == 200
        client.headers["Mcp-Session-Id"] = initialized.headers["mcp-session-id"]
        ready = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
        assert ready.status_code in (200, 202)

        def call(arguments, request_id):
            response = client.post("/mcp", json={
                "jsonrpc": "2.0", "id": request_id, "method": "tools/call",
                "params": {"name": "get_timesheets", "arguments": arguments},
            })
            assert response.status_code == 200
            body = _rpc(response)
            assert "error" not in body
            result = body["result"]
            assert result.get("isError") is False
            return response.status_code, _rows(result)

        all_code, all_rows = call({"limit": 20}, 2)
        starts = [row["begin_datetime"] for row in all_rows]
        assert starts == sorted(starts, reverse=True)
        assert all_rows, "stand has no timesheet rows for a nonempty range proof"
        day = date.fromisoformat(starts[0][:10])
        range_code, range_rows = call({"date_from": day.isoformat(), "date_to": day.isoformat(), "limit": 20}, 3)
        assert range_rows, "range built from a known shift returned no rows"
        lower = f"{day.isoformat()} 00:00:00"
        upper = f"{(day + timedelta(days=1)).isoformat()} 00:00:00"
        assert all(row["end_datetime"] > lower and row["begin_datetime"] < upper for row in range_rows)
        assert [row["begin_datetime"] for row in range_rows] == sorted(
            [row["begin_datetime"] for row in range_rows], reverse=True
        )
        print("GET_TIMESHEETS_DEFAULT", all_code, json.dumps({
            "row_count": len(all_rows), "begin_dates": [value[:10] for value in starts],
        }))
        print("GET_TIMESHEETS_RANGE", range_code, json.dumps({
            "row_count": len(range_rows),
            "begin_dates": [row["begin_datetime"][:10] for row in range_rows],
            "end_dates": [row["end_datetime"][:10] for row in range_rows],
            "overlap_valid": True,
        }))
