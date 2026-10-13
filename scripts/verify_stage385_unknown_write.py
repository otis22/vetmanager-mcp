#!/usr/bin/env python3
"""Devtr6 probe: lose a PUT response, reconcile by ID, then restore the row."""

import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

from host_resolver import resolve_vetmanager_host
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


ROW_ID = 816  # Dedicated test goodSaleParam, clinic 1.
PATH = f"/rest/api/goodSaleParam/{ROW_ID}"


def credentials() -> tuple[str, str]:
    values = {}
    for line in Path(".env").read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            name, value = line.split("=", 1)
            values[name.strip()] = value.strip().strip('"').strip("'")
    domain, key = values.get("TEST_DOMAIN"), values.get("TEST_API_KEY")
    if domain != "devtr6" or not key:
        raise SystemExit("Requires the devtr6 TEST_DOMAIN and TEST_API_KEY")
    return domain, key


async def main() -> None:
    domain, key = credentials()
    host = await resolve_vetmanager_host(domain)
    if "devtr6" not in host:
        raise SystemExit("Resolved host is not the devtr6 test contour")
    async with httpx.AsyncClient(base_url=host, headers={
        "X-REST-API-KEY": key, "X-USE-XALLHEADER": "true"}, timeout=30) as direct:
        async def read_status() -> tuple[int, str]:
            response = await direct.get(PATH)
            response.raise_for_status()
            row = response.json()["data"]["goodSaleParam"]
            if (int(row["id"]), int(row["good_id"]), int(row["clinic_id"]),
                    int(row["unit_sale_id"])) != (ROW_ID, 418, 1, 0):
                raise RuntimeError("Dedicated test row identity changed")
            return response.status_code, row["status"]

        before_http, before = await read_status()
        if before != "active":
            raise RuntimeError("Dedicated test row must start active")
        headers, runtime = patch_runtime_credentials(domain, key)
        with headers, runtime:
            preview = (await mcp.call_tool("set_good_sale_param_status", {
                "sale_param_id": ROW_ID, "clinic_id": 1,
                "target_status": "disabled",
            })).structured_content
        if preview.get("applied") is not False or not preview.get("confirmation"):
            raise RuntimeError("No safe preview")

        actual_puts: list[int] = []
        original_request = httpx.AsyncClient.request

        async def lose_response(client, method, url, **kwargs):
            response = await original_request(client, method, url, **kwargs)
            if method.upper() == "PUT" and urlsplit(str(url)).path == PATH:
                actual_puts.append(response.status_code)
                response.raise_for_status()
                raise httpx.ReadError("simulated response loss", request=response.request)
            return response

        try:
            with patch.object(httpx.AsyncClient, "request", lose_response):
                with headers, runtime:
                    try:
                        await mcp.call_tool("set_good_sale_param_status", {
                            "sale_param_id": ROW_ID, "clinic_id": 1,
                            "target_status": "disabled", "confirm": True,
                            "confirmation": preview["confirmation"],
                        })
                    except Exception as exc:
                        if "outcome is unknown; read the row before retrying" not in str(exc):
                            raise
                    else:
                        raise RuntimeError("Lost response was reported as success")
            read_http, reconciled = await read_status()  # No second write.
            if len(actual_puts) != 1 or not 200 <= actual_puts[0] < 300 or reconciled != "disabled":
                raise RuntimeError("Unknown write was replayed or readback failed")
            print(json.dumps({"write_http": actual_puts, "tool_outcome": "unknown",
                              "read_http": read_http, "readback": reconciled,
                              "automatic_retry": False}))
        finally:
            if (await read_status())[1] != "active":
                restored = await direct.put(PATH, json={"status": "active"})
                restored.raise_for_status()
                restore_http, status = await read_status()
                if status != "active":
                    raise RuntimeError("Dedicated test row was not restored")
                print(json.dumps({"restore_http": restored.status_code,
                                  "verify_http": restore_http, "restored": True}))


if __name__ == "__main__":
    asyncio.run(main())
