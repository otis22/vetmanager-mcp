#!/usr/bin/env python3
"""Opt-in read-only probe for scalar list-filter field names.

Requires TEST_DOMAIN and TEST_API_KEY. Output deliberately contains only an
entity name, a field name and an HTTP status; values and credentials never
leave process memory or reach stdout.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from auth.context import VetmanagerAuthContext, VETMANAGER_AUTH_MODE_DOMAIN_API_KEY
from host_resolver import resolve_vetmanager_host


ENTITIES = {
    "cassaclose": "/rest/api/cassaclose",
    "payment": "/rest/api/payment",
    "invoice": "/rest/api/invoice",
}
PROBE_VALUE = 0
REQUEST_GAP_SECONDS = 0.1


def _scalar_fields(row: dict[str, Any]) -> list[str]:
    return sorted(
        field for field, value in row.items()
        if value is None or isinstance(value, (bool, int, float, str))
    )


def _rows(payload: Any, entity: str) -> list[dict[str, Any]]:
    data = payload.get("data", {}) if isinstance(payload, dict) else {}
    rows = data.get(entity, []) if isinstance(data, dict) else data
    return rows if isinstance(rows, list) else []


async def _probe_entity(
    client: httpx.AsyncClient, base_url: str, entity: str, path: str
) -> None:
    response = await client.get(f"{base_url}{path}", params={"limit": 1, "offset": 0})
    if response.status_code != 200:
        print(f"{entity} LIST {response.status_code}")
        return
    rows = _rows(response.json(), entity)
    if not rows or not isinstance(rows[0], dict):
        print(f"{entity} NO_ROWS")
        return
    for field in _scalar_fields(rows[0]):
        response = await client.get(
            f"{base_url}{path}",
            params={
                "limit": 1,
                "offset": 0,
                "filter": json.dumps(
                    [{"property": field, "operator": "=", "value": PROBE_VALUE}],
                    separators=(",", ":"),
                ),
            },
        )
        print(f"{entity} {field} {response.status_code}")
        await asyncio.sleep(REQUEST_GAP_SECONDS)


async def main() -> None:
    domain = os.environ.get("TEST_DOMAIN", "")
    api_key = os.environ.get("TEST_API_KEY", "")
    if not domain or not api_key:
        raise SystemExit("TEST_DOMAIN and TEST_API_KEY are required")
    if domain != "devtr6":
        raise SystemExit("This probe is restricted to TEST_DOMAIN=devtr6")
    base_url = await resolve_vetmanager_host(domain)
    auth = VetmanagerAuthContext(
        auth_mode=VETMANAGER_AUTH_MODE_DOMAIN_API_KEY,
        domain=domain,
        credential=api_key,
    )
    async with httpx.AsyncClient(headers=auth.build_headers(), timeout=30.0) as client:
        for entity, path in ENTITIES.items():
            await _probe_entity(client, base_url, entity, path)


if __name__ == "__main__":
    asyncio.run(main())
