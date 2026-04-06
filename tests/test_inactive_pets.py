"""Tests for get_inactive_pets tool."""

import pytest
import respx
import httpx

from server import mcp
from tests.runtime_factories import (
    make_client_with_resolved_runtime,
    patch_runtime_credentials,
)

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch(domain=DOMAIN, api_key=API_KEY):
    return patch_runtime_credentials(
        domain,
        api_key,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_returns_pets_without_recent_visits():
    """Pets with no admission, invoice, or medical card after cutoff are inactive."""
    billing_mock()

    # Pet 1 has a recent admission -> active
    # Pet 2 has a recent invoice -> active
    # Pet 3 has a recent medical card -> active
    # Pet 4 has nothing recent -> inactive
    # Pet 5 has nothing recent -> inactive

    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 5,
                "pet": [
                    {"id": 1, "alias": "Rex"},
                    {"id": 2, "alias": "Luna"},
                    {"id": 3, "alias": "Max"},
                    {"id": 4, "alias": "Bella"},
                    {"id": 5, "alias": "Charlie"},
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 1,
                "admission": [
                    {"id": 10, "patient_id": 1, "admission_date": "2026-04-01 10:00:00"},
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 1,
                "invoice": [
                    {"id": 20, "pet_id": 2, "date": "2026-03-15"},
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 1,
                "medicalCards": [
                    {"id": 30, "patient_id": 3, "date_create": "2026-03-20"},
                ],
            }
        })
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6, "limit": 50})

    import json
    data = json.loads(result.content[0].text)
    assert data["total_pets"] == 5
    assert data["total_inactive"] == 2
    inactive_ids = {pet["id"] for pet in data["inactive_pets"]}
    assert inactive_ids == {4, 5}
    assert data["months"] == 6


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_all_active_returns_empty():
    """When all pets have recent visits, inactive list is empty."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 2,
                "pet": [
                    {"id": 1, "alias": "Rex"},
                    {"id": 2, "alias": "Luna"},
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 2,
                "admission": [
                    {"id": 10, "patient_id": 1, "admission_date": "2026-04-01 10:00:00"},
                    {"id": 11, "patient_id": 2, "admission_date": "2026-03-20 14:00:00"},
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )

    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "medicalCards": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6})

    import json
    data = json.loads(result.content[0].text)
    assert data["total_inactive"] == 0
    assert data["inactive_pets"] == []


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_respects_limit():
    """Limit parameter caps the returned inactive pets."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 5,
                "pet": [
                    {"id": i, "alias": f"Pet{i}"} for i in range(1, 6)
                ],
            }
        })
    )

    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "admission": []}})
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "medicalCards": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6, "limit": 2})

    import json
    data = json.loads(result.content[0].text)
    assert data["total_inactive"] == 5
    assert len(data["inactive_pets"]) == 2
