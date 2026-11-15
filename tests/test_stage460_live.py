"""Read-only stage 460 proof on the .env test contour; prints no card text."""

import os
from unittest.mock import patch

import httpx
import pytest

from depersonalization import sanitize_tool_result
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient

pytestmark = [pytest.mark.real_api, pytest.mark.skipif(
    not (os.environ.get("TEST_DOMAIN") and os.environ.get("TEST_API_KEY")),
    reason=".env test contour unavailable",
)]


@pytest.mark.asyncio
async def test_stage460_live_three_projected_lists(capsys):
    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"], is_depersonalized=True)
    observed = []
    original_request = httpx.AsyncClient.request

    async def capture(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/" in str(url):
            observed.append((method, response.status_code))
        return response

    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        candidate = None
        for offset in range(0, 1000, 100):
            page = await VetmanagerClient().get("/rest/api/MedicalCards", params={
                "limit": 100, "offset": offset,
                "sort": '[{"property":"id","direction":"DESC"}]',
            })
            rows = page.get("data", {}).get("medicalCards") or []
            candidate = next((row for row in rows if row.get("recomendation")), None)
            if candidate or len(rows) < 100:
                break
        assert candidate is not None, "test contour has no recent card with recommendation"
        card_id = int(candidate["id"])
        pet_id = int(candidate["patient_id"])
        day = str(candidate["date_create"])[:10]
        pet = await VetmanagerClient().get(f"/rest/api/pet/{pet_id}")
        client_id = int(pet["data"]["pet"]["owner_id"])
        expected = sanitize_tool_result({"recomendation": candidate["recomendation"]})["recomendation"]
        calls = (
            ("get_medical_cards", {"pet_id": pet_id}),
            ("get_medical_cards_by_date", {"date": day}),
            ("get_medical_cards_by_client_id", {"client_id": client_id}),
        )
        safe_body = {}
        for name, args in calls:
            response = await mcp.call_tool(name, {
                **args, "limit": 100, "sort": [{"property": "id", "direction": "DESC"}],
                "fields": ["id", "recommendation"],
            })
            assert not response.is_error, f"{name}: MCP error"
            body = response.structured_content
            rows = body.get("data", body).get("medicalCards") or body.get("medical_cards") or []
            matching = next((row for row in rows if row.get("id") == card_id), None)
            assert matching is not None, f"{name}: sampled card outside first 100 rows"
            assert set(matching) == {"id", "recommendation"}, f"{name}: unexpected fields"
            matches_expected = matching["recommendation"] == expected
            assert matches_expected, f"{name}: recommendation mismatch"
            safe_body[name] = {"matched": True, "recommendation_present": True,
                               "text_equal_after_cleaning": True, "row_keys": sorted(matching)}

    assert observed and all(method == "GET" and code in {200, 401} for method, code in observed)
    assert observed[-1] == ("GET", 200)
    with capsys.disabled():
        print(f"STAGE460_LIVE upstream_final=GET/200 retry_401={sum(code == 401 for _, code in observed)} body={safe_body}")
