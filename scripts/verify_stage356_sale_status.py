#!/usr/bin/env python3
"""Live devtr6-only smoke: disable and restore one known test sale option."""

import asyncio
import json
from pathlib import Path
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx

from host_resolver import resolve_vetmanager_host
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


PARAM_ID = 816  # Test good 418, clinic 1, sale unit 0; checked before this probe.
CLINIC_ID = 1


def test_credentials() -> tuple[str, str]:
    values = {}
    for line in Path(".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    domain, key = values.get("TEST_DOMAIN"), values.get("TEST_API_KEY")
    if domain != "devtr6" or not key:
        raise SystemExit("This probe requires devtr6 TEST_DOMAIN and TEST_API_KEY")
    return domain, key


def row(body: dict) -> dict:
    data = body.get("data", {})
    result = data.get("goodSaleParam") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("Unexpected sale parameter response")
    return result


async def main() -> None:
    domain, key = test_credentials()
    host = await resolve_vetmanager_host(domain)
    if "devtr6" not in host:
        raise SystemExit("Resolved host is not the devtr6 test contour")
    headers = {"X-REST-API-KEY": key, "X-USE-XALLHEADER": "true"}
    async with httpx.AsyncClient(base_url=host, headers=headers, timeout=30) as direct:
        async def read() -> dict:
            response = await direct.get(f"/rest/api/goodSaleParam/{PARAM_ID}")
            response.raise_for_status()
            value = row(response.json())
            print(json.dumps({"read_http": response.status_code,
                              "body": {field: value.get(field) for field in
                                       ("id", "good_id", "clinic_id", "unit_sale_id", "status")}}))
            if (int(value["id"]), int(value["good_id"]), int(value["clinic_id"]),
                    int(value["unit_sale_id"])) != (PARAM_ID, 418, CLINIC_ID, 0):
                raise RuntimeError("Known test row changed identity")
            return value

        original = await read()
        if original.get("status") != "active":
            raise RuntimeError("Test row must start active; refusing to change it")
        statuses = []
        original_request = httpx.AsyncClient.request

        async def recorded_request(client, method, url, **kwargs):
            response = await original_request(client, method, url, **kwargs)
            if urlsplit(str(url)).path == f"/rest/api/goodSaleParam/{PARAM_ID}":
                statuses.append((method.upper(), response.status_code))
            return response

        async def tool(target: str) -> dict:
            header_patch, runtime_patch = patch_runtime_credentials(domain, key)
            with header_patch, runtime_patch:
                preview = (await mcp.call_tool("set_good_sale_param_status", {
                    "sale_param_id": PARAM_ID, "clinic_id": CLINIC_ID,
                    "target_status": target,
                })).structured_content
            if preview.get("applied") is not False or not preview.get("confirmation"):
                raise RuntimeError("Tool did not return a safe preview")
            with header_patch, runtime_patch:
                answer = (await mcp.call_tool("set_good_sale_param_status", {
                    "sale_param_id": PARAM_ID, "clinic_id": CLINIC_ID,
                    "target_status": target, "confirm": True,
                    "confirmation": preview["confirmation"],
                })).structured_content
            print(json.dumps({"target": target, "mcp_body": answer}))
            return answer

        try:
            with patch.object(httpx.AsyncClient, "request", recorded_request):
                await tool("disabled")
            if (await read()).get("status") != "disabled":
                raise RuntimeError("Disable was not confirmed by direct read")
        finally:
            if (await read()).get("status") != "active":
                with patch.object(httpx.AsyncClient, "request", recorded_request):
                    try:
                        await tool("active")
                    except Exception:
                        response = await direct.put(
                            f"/rest/api/goodSaleParam/{PARAM_ID}", json={"status": "active"})
                        print(json.dumps({"emergency_restore_http": response.status_code}))
                if (await read()).get("status") != "active":
                    raise RuntimeError("Test row was not restored")
        print(json.dumps({"tool_upstream_http": statuses, "restored": True}))


if __name__ == "__main__":
    asyncio.run(main())
