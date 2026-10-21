"""Opt-in read-only pagination proof on the .env API-key contour."""

import json
import os
from unittest.mock import patch

import httpx
import pytest

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


@pytest.mark.real_api
@pytest.mark.asyncio
@pytest.mark.skipif(not os.environ.get("TEST_DOMAIN") or not os.environ.get("TEST_API_KEY"),
                    reason=".env test contour credentials absent")
async def test_stage429_live_client_cards_page(capsys):
    original_request = httpx.AsyncClient.request
    observed = []

    async def capture(client, method, url, **kwargs):
        response = await original_request(client, method, url, **kwargs)
        if "/rest/api/MedicalCards" in str(url):
            observed.append((method, response.status_code))
        return response

    headers, runtime = patch_runtime_credentials(
        os.environ["TEST_DOMAIN"], os.environ["TEST_API_KEY"])
    with headers, runtime, patch.object(httpx.AsyncClient, "request", capture):
        pets_response = await mcp.call_tool("get_pets", {"limit": 20})
        assert not pets_response.is_error
        pets = (pets_response.structured_content or {}).get("data", {}).get("pet", [])
        owner_id = next((pet.get("client_id") for pet in pets if pet.get("client_id")), None)
        assert owner_id is not None, "live pet sample has no owner client_id"
        response = await mcp.call_tool("get_medical_cards_by_client_id", {
            "client_id": int(owner_id), "limit": 1, "offset": 0,
        })

    assert not response.is_error
    body = response.structured_content or {}
    safe_body = {
        "success": body.get("success"),
        "medical_cards_count": body.get("medical_cards_count"),
        "medical_cards_total": body.get("medical_cards_total"),
        "medical_cards_has_more": body.get("medical_cards_has_more"),
        "pets_truncated": body.get("pets_truncated"),
    }
    with capsys.disabled():
        print(f"STAGE429_CLIENT_CARDS codes={observed} body={json.dumps(safe_body)}")
    assert observed == [("GET", 200)]
    assert safe_body["success"] is True
    assert safe_body["medical_cards_count"] in (0, 1)
    assert isinstance(safe_body["medical_cards_total"], int)
    expected_has_more = (
        None if safe_body["medical_cards_count"] == 0
        and safe_body["medical_cards_total"] > 0
        else safe_body["medical_cards_count"] < safe_body["medical_cards_total"]
    )
    assert safe_body["medical_cards_has_more"] is expected_has_more
