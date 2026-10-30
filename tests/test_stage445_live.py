"""Read-only staff-filter audit probe on the .env test contour."""

import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient

pytestmark = pytest.mark.real_api


@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour unavailable")
async def test_stage445_live_both_role_filters(capsys):
    domain, api_key = os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"]
    headers, runtime = patch_runtime_credentials(domain, api_key)
    observed = []
    original = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original(client, method, url, **kwargs)
        if "/rest/api/" in str(url):
            observed.append((method, response.status_code))
        return response

    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        latest = await VetmanagerClient().get("/rest/api/MedicalCards", params={
            "limit": 100, "sort": '[{"property":"date_create","direction":"DESC"}]'})
        candidates = latest.get("data", {}).get("medicalCards") or []
        card = next((row for row in candidates if row.get("doctor_id") and row.get("creator_id")), None)
        assert card is not None, "test contour needs a card with doctor and creator IDs"
        day = str(card["date_create"])[:10]
        doctor, creator = int(card["doctor_id"]), int(card["creator_id"])
        base = {"date_from": day, "date_to": day, "limit": 100, "offset": 0,
                "sort": [{"property": "date_create", "direction": "DESC"}]}
        variants = (
            base,
            {**base, "doctor_id": doctor},
            {**base, "creator_id": creator},
            {**base, "doctor_id": doctor, "creator_id": creator},
        )
        results = [await mcp.call_tool("get_medical_cards_by_date", args) for args in variants]
        catalogue = {tool.name: tool.to_mcp_tool().description for tool in await mcp.list_tools()}

    assert all(not result.is_error for result in results)
    rows = [result.structured_content["medical_cards"] for result in results]
    assert rows[3], "combined role filters must return a sampled card"
    assert all(int(row["doctor_id"]) == doctor for row in rows[1])
    assert all(int(row["creator_id"]) == creator for row in rows[2])
    assert all(int(row["doctor_id"]) == doctor and int(row["creator_id"]) == creator
               for row in rows[3])
    assert "Prefer the server-side doctor_id or creator_id filter" in catalogue["get_medical_cards_by_date"]
    assert observed and all(method == "GET" and status == 200 for method, status in observed)
    with capsys.disabled():
        print("STAGE445_LIVE upstream_requests_all_GET_200=true body=" + str({
            "unfiltered": len(rows[0]), "doctor_only": len(rows[1]),
            "creator_only": len(rows[2]), "both": len(rows[3]),
            "both_rows_match_roles": True, "filter_effect_unproven": True,
        }))
