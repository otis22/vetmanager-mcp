"""Tests for get_inactive_pets tool."""

import json

import pytest
import respx
import httpx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

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


def _mock_all_endpoints(
    pets: list[dict],
    admissions: list[dict] | None = None,
    invoices: list[dict] | None = None,
    medcards: list[dict] | None = None,
):
    """Set up respx mocks for all 4 endpoints used by get_inactive_pets."""
    admissions = admissions or []
    invoices = invoices or []
    medcards = medcards or []

    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": len(pets), "pet": pets}
        })
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": len(admissions), "admission": admissions}
        })
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": len(invoices), "invoice": invoices}
        })
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": len(medcards), "medicalCards": medcards}
        })
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_returns_pets_without_recent_visits():
    """Pets with no admission, invoice, or medical card after cutoff are inactive."""
    billing_mock()
    _mock_all_endpoints(
        pets=[
            {"id": 1, "alias": "Rex", "status": "alive"},
            {"id": 2, "alias": "Luna", "status": "alive"},
            {"id": 3, "alias": "Max", "status": "alive"},
            {"id": 4, "alias": "Bella", "status": "alive"},
            {"id": 5, "alias": "Charlie", "status": "alive"},
        ],
        admissions=[{"id": 10, "patient_id": 1, "admission_date": "2026-04-01 10:00:00"}],
        invoices=[{"id": 20, "pet_id": 2, "invoice_date": "2026-03-15", "status": "exec"}],
        medcards=[{"id": 30, "patient_id": 3, "date_create": "2026-03-20"}],
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6, "limit": 50})

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
    _mock_all_endpoints(
        pets=[
            {"id": 1, "alias": "Rex", "status": "alive"},
            {"id": 2, "alias": "Luna", "status": "alive"},
        ],
        admissions=[
            {"id": 10, "patient_id": 1, "admission_date": "2026-04-01 10:00:00"},
            {"id": 11, "patient_id": 2, "admission_date": "2026-03-20 14:00:00"},
        ],
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6})

    data = json.loads(result.content[0].text)
    assert data["total_inactive"] == 0
    assert data["inactive_pets"] == []


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_respects_limit():
    """Limit parameter caps the returned inactive pets."""
    billing_mock()
    _mock_all_endpoints(
        pets=[{"id": i, "alias": f"Pet{i}", "status": "alive"} for i in range(1, 6)],
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"months": 6, "limit": 2})

    data = json.loads(result.content[0].text)
    assert data["total_inactive"] == 5
    assert len(data["inactive_pets"]) == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_sends_correct_api_filters():
    """Verify the tool sends correct filter parameters to each API endpoint."""
    billing_mock()

    admission_route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "admission": []}})
    )
    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "medicalCards": []}})
    )
    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "pet": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_pets", {"months": 3})

    # Check admission filter uses admission_date
    adm_filter = admission_route.calls.last.request.url.params.get("filter", "")
    assert "admission_date" in adm_filter
    assert ">=" in adm_filter

    # Check invoice filter uses invoice_date (not "date") and excludes deleted
    inv_filter = invoice_route.calls.last.request.url.params.get("filter", "")
    assert "invoice_date" in inv_filter
    assert "deleted" in inv_filter

    # Check medcard filter uses date_create
    mc_filter = medcard_route.calls.last.request.url.params.get("filter", "")
    assert "date_create" in mc_filter

    # Check pet filter uses status=alive
    pet_filter = pet_route.calls.last.request.url.params.get("filter", "")
    assert "alive" in pet_filter
