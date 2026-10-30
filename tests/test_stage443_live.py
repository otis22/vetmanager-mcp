"""Read-only phase probe on the .env test contour; no clinical body is logged."""

import json
import os
import time

import httpx
import pytest

from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient

pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour unavailable")
async def test_stage443_live_medical_card_phase_probe():
    headers, runtime = patch_runtime_credentials(os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    with headers, runtime:
        vc = VetmanagerClient()
        started = time.monotonic()
        origin = await vc._resolve_host()
        resolved_at = time.monotonic()
        params = {"limit": 10, "offset": 0, "filter": json.dumps([
            {"property": "date_create", "operator": ">=", "value": "2026-09-24 00:00:00"},
            {"property": "date_create", "operator": "<", "value": "2026-09-25 00:00:00"},
        ])}
        async with httpx.AsyncClient(timeout=30) as client:
            async with client.stream("GET", f"{origin}/rest/api/MedicalCards",
                                     headers=vc._headers(), params=params) as response:
                headers_at = time.monotonic()
                body = await response.aread()
                body_at = time.monotonic()
    assert response.status_code == 200
    data = json.loads(body).get("data", {})
    rows = data.get("medicalCards") or []
    assert isinstance(rows, list)
    print("STAGE443_LIVE", {"upstream_http": response.status_code,
        "body": {"rows": len(rows), "bytes": len(body)},
        "phase_ms": {"resolve": round((resolved_at-started)*1000),
                     "headers": round((headers_at-resolved_at)*1000),
                     "transfer": round((body_at-headers_at)*1000)}})
