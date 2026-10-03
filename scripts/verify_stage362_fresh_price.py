#!/usr/bin/env python3
"""Live devtr6-only probe: stale expected price refuses; success restores row."""

import asyncio
from decimal import Decimal
import json
import os
from urllib.parse import urlsplit
from unittest.mock import patch

import httpx

from host_resolver import resolve_vetmanager_host
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


PARAM_ID = 816  # Known test good 418, clinic 1, unit 0.


def sale_row(body: dict) -> dict:
    row = body.get("data", {}).get("goodSaleParam")
    if not isinstance(row, dict):
        raise RuntimeError("Unexpected sale parameter response")
    return row


async def main() -> None:
    domain, key = os.getenv("TEST_DOMAIN", ""), os.getenv("TEST_API_KEY", "")
    if domain != "devtr6" or not key:
        raise SystemExit("This probe requires devtr6 TEST_DOMAIN and TEST_API_KEY")
    host = await resolve_vetmanager_host(domain)
    if "devtr6" not in host:
        raise SystemExit("Resolved host is not the devtr6 test contour")
    headers = {"X-REST-API-KEY": key, "X-USE-XALLHEADER": "true"}
    path = f"/rest/api/goodSaleParam/{PARAM_ID}"
    async with httpx.AsyncClient(base_url=host, headers=headers, timeout=30) as direct:
        async def read() -> dict:
            response = await direct.get(path)
            response.raise_for_status()
            row = sale_row(response.json())
            if (int(row.get("id") or 0), int(row.get("good_id") or 0),
                    int(row.get("clinic_id") or 0), int(row.get("unit_sale_id") or 0)) != (
                    PARAM_ID, 418, 1, 0):
                raise RuntimeError("Known test row changed identity")
            print(json.dumps({"direct_read_http": response.status_code,
                              "body": {"id": row["id"], "price": row.get("price"),
                                       "status": row.get("status")}}))
            return row

        async def direct_price(value: str) -> None:
            response = await direct.put(path, json={"price": value})
            print(json.dumps({"direct_put_http": response.status_code,
                              "body": {"success": response.json().get("success")}}))
            response.raise_for_status()
            if Decimal(str((await read()).get("price"))) != Decimal(value):
                raise RuntimeError("Direct test price change was not confirmed")

        async def tool(name: str, **args) -> dict:
            header_patch, runtime_patch = patch_runtime_credentials(domain, key)
            with header_patch, runtime_patch:
                result = await mcp.call_tool(name, args)
            return result.structured_content

        original = await read()
        if original.get("status") != "active" or original.get("price_formation") == "increase":
            raise RuntimeError("Test row must be active with a directly writable price")
        original_price = str(original["price"])
        probe_price = str(Decimal(original_price) + Decimal("1.00"))
        applied_decimal = Decimal(original_price) + Decimal("2.00")
        applied_price = float(applied_decimal)
        tool_requests: list[tuple[str, int]] = []
        original_request = httpx.AsyncClient.request

        async def recorded_request(client, method, url, **kwargs):
            response = await original_request(client, method, url, **kwargs)
            if urlsplit(str(url)).path == path:
                tool_requests.append((method.upper(), response.status_code))
            return response

        try:
            warm = await tool("get_good_sale_param_by_id", param_id=PARAM_ID)
            if Decimal(str(sale_row(warm)["price"])) != Decimal(original_price):
                raise RuntimeError("Could not warm the expected price in MCP cache")
            await direct_price(probe_price)
            with patch.object(httpx.AsyncClient, "request", recorded_request):
                try:
                    await tool("update_good_sale_price", sale_param_id=PARAM_ID,
                               new_price=applied_price, expected_price=original_price,
                               scope="row", confirm=True)
                except Exception as exc:
                    refusal = str(exc)
                else:
                    raise RuntimeError("Stale expected price was accepted")
            if "expected_price" not in refusal or probe_price not in refusal:
                raise RuntimeError("Refusal did not include the fresh price")
            if any(method == "PUT" for method, _ in tool_requests):
                raise RuntimeError("Refused tool call sent a PUT")
            print(json.dumps({"refusal": refusal, "tool_upstream_http": tool_requests}))
            with patch.object(httpx.AsyncClient, "request", recorded_request):
                answer = await tool("update_good_sale_price", sale_param_id=PARAM_ID,
                                    new_price=applied_price, expected_price=probe_price,
                                    scope="row", confirm=True)
            print(json.dumps({"confirmed_tool_body": answer,
                              "tool_upstream_http": tool_requests}))
            if not answer.get("applied") or Decimal(str((await read())["price"])) != applied_decimal:
                raise RuntimeError("Confirmed tool price was not observed")
        finally:
            # Always attempt restoration, even when a preceding GET failed.
            await direct_price(original_price)
            if Decimal(str((await read())["price"])) != Decimal(original_price):
                raise RuntimeError("Test row price was not restored")
        print(json.dumps({"restored": True, "original_price": original_price}))


if __name__ == "__main__":
    asyncio.run(main())
