#!/usr/bin/env python3
"""Read-only devtr6 probe for invoice money semantics; prints no credentials or PII."""

import asyncio
from decimal import Decimal, ROUND_HALF_UP
import os

import httpx

from host_resolver import resolve_vetmanager_host
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


def _rows(body: dict, key: str) -> list[dict]:
    data = body.get("data", {})
    rows = data.get(key, []) if isinstance(data, dict) else []
    return rows if isinstance(rows, list) else [rows] if isinstance(rows, dict) else []


async def main() -> None:
    domain = os.environ.get("TEST_DOMAIN", "")
    key = os.environ.get("TEST_API_KEY", "")
    if domain != "devtr6" or not key:
        raise SystemExit("Stage 340 probe requires TEST_DOMAIN=devtr6 and a test API key")
    host = await resolve_vetmanager_host(domain)
    if "devtr6" not in host or "212.193.59.219" in host:
        raise SystemExit("Resolved host is not the devtr6 test contour")
    headers = {"X-REST-API-KEY": key, "X-USE-XALLHEADER": "true"}
    async with httpx.AsyncClient(base_url=host, headers=headers, timeout=30) as client:
        for offset in range(0, 3000, 100):
            response = await client.get("/rest/api/invoice", params={"limit": 100, "offset": offset})
            response.raise_for_status()
            invoices = _rows(response.json(), "invoice")
            for candidate in invoices:
                if candidate.get("status") != "exec":
                    continue
                discount = Decimal(str(candidate.get("discount") or "0"))
                if not discount:
                    continue
                detail_response = await client.get(f"/rest/api/invoice/{int(candidate['id'])}")
                if detail_response.status_code != 200:
                    continue
                invoice_rows = _rows(detail_response.json(), "invoice")
                if not invoice_rows:
                    continue
                invoice = invoice_rows[0]
                if invoice.get("status") != "exec":
                    continue
                lines = invoice.get("invoiceDocuments")
                if not isinstance(lines, list) or not lines:
                    continue
                base = sum((Decimal(str(line["price"])) for line in lines), Decimal("0"))
                increase = Decimal(str(invoice.get("increase") or "0"))
                actual = Decimal(str(invoice["amount"]))
                expected = base * (Decimal("1") - discount / 100) * (Decimal("1") + increase / 100)
                expected = expected.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                difference = abs(actual - expected)
                rouble_discount = sum((
                    Decimal(str(line["default_price"]))
                    - Decimal(str(line["price"]))
                    * (Decimal("1") - discount / 100)
                    * (Decimal("1") + increase / 100)
                    for line in lines
                ), Decimal("0"))
                print(f"discount_pct={discount} increase_pct={increase} line_total={base} "
                      f"amount={actual} expected={expected} difference={difference} "
                      f"rouble_discount={rouble_discount} lines={len(lines)}")
                if difference > Decimal("0.05"):
                    raise SystemExit("Invoice amount differs from the percentage formula")
                headers_patch, runtime_patch = patch_runtime_credentials(domain, key)
                with headers_patch, runtime_patch:
                    listed = await mcp.call_tool("get_invoices", {"limit": 100, "offset": offset})
                listing_body = listed.structured_content
                if not isinstance(listing_body, dict):
                    raise SystemExit("MCP get_invoices returned an unexpected response")
                listed_ids = {int(row["id"]) for row in _rows(listing_body, "invoice")}
                if int(candidate["id"]) not in listed_ids:
                    raise SystemExit("MCP get_invoices did not return the checked invoice")
                print(f"get_invoices_body_keys={sorted(listing_body)} "
                      f"read_http={detail_response.status_code} status={invoice.get('status')}")
                return
            if len(invoices) < 100:
                break
    raise SystemExit("No readable discounted invoice with line items found on devtr6")


if __name__ == "__main__":
    asyncio.run(main())
