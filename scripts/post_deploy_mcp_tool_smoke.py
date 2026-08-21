#!/usr/bin/env python3
"""Read-only public MCP smoke: initialize, tools/list, then get_users(limit=1)."""

from __future__ import annotations

import os
import sys
import time
import json

import httpx

DEFAULT_BASE_URL = "https://vetmanager-mcp.vromanichev.ru"


def _request(client: httpx.Client, method: str, params: dict, request_id: int) -> tuple[dict, httpx.Headers]:
    response = client.post("/mcp", json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
    response.raise_for_status()
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        payload = next(
            (json.loads(line.removeprefix("data: ")) for line in response.text.splitlines() if line.startswith("data: ")),
            None,
        )
    else:
        payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"MCP {method} returned an invalid JSON-RPC response")
    if payload.get("id") != request_id or "error" in payload or "result" not in payload:
        raise RuntimeError(f"MCP {method} returned an invalid JSON-RPC response")
    return payload["result"], response.headers


def main() -> int:
    token = os.environ.get("PROD_SMOKE_BEARER_TOKEN", "").strip()
    if not token:
        print("Missing PROD_SMOKE_BEARER_TOKEN.", file=sys.stderr)
        return 2
    base_url = (sys.argv[1] if len(sys.argv) > 1 else DEFAULT_BASE_URL).rstrip("/")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json, text/event-stream"}
    for attempt in range(1, 11):
        try:
            with httpx.Client(base_url=base_url, headers=headers, timeout=30.0) as client:
                initialized, response_headers = _request(client, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "post-deploy-smoke", "version": "1"}}, 1)
                if "protocolVersion" not in initialized:
                    raise RuntimeError("MCP initialize result lacks protocolVersion")
                session_id = response_headers.get("mcp-session-id")
                if session_id:
                    client.headers["Mcp-Session-Id"] = session_id
                notification = client.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                notification.raise_for_status()
                tools, _ = _request(client, "tools/list", {}, 2)
                tools = tools.get("tools", [])
                if "get_users" not in {tool.get("name") for tool in tools}:
                    raise RuntimeError("MCP tools/list lacks required read-only tool")
                call, _ = _request(client, "tools/call", {"name": "get_users", "arguments": {"limit": 1}}, 3)
                if call.get("isError"):
                    raise RuntimeError("MCP read-only tool returned an error")
            print("MCP read-only tool smoke passed.")
            return 0
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {502, 503, 504}:
                print(f"MCP tool smoke failed: {type(exc).__name__}", file=sys.stderr)
                return 1
            if attempt == 10:
                print(f"MCP tool smoke failed: {type(exc).__name__}", file=sys.stderr)
                return 1
            time.sleep(3)
        except (httpx.HTTPStatusError, ValueError, RuntimeError) as exc:
            print(f"MCP tool smoke failed: {type(exc).__name__}", file=sys.stderr)
            return 1


if __name__ == "__main__":
    raise SystemExit(main())
