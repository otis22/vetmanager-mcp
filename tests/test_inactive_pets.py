"""Tests for get_inactive_pets tool — per-pet visit detection algorithm."""

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


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _client_response(clients):
    return httpx.Response(200, json={"data": {"totalCount": len(clients), "client": clients}})


def _pet_response(pets):
    return httpx.Response(200, json={"data": {"totalCount": len(pets), "pet": pets}})


def _invoice_response(invoices):
    return httpx.Response(200, json={"data": {"totalCount": len(invoices), "invoice": invoices}})


def _medcards_response(medcards):
    return httpx.Response(
        200, json={"data": {"totalCount": len(medcards), "medicalCards": medcards}}
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_returns_pets_at_last_visit_via_invoice():
    """Pet with matching invoice on/after client.last_visit_date is included with source=invoice."""
    billing_mock()

    # 1 inactive client, 2 alive pets — only Rex was at the last visit (has invoice)
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 1,
                "last_name": "Doe",
                "first_name": "John",
                "middle_name": "",
                "cell_phone": "+1000",
                "last_visit_date": "2024-12-15 14:30:00",
            }
        ])
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 10, "alias": "Rex", "type_id": 1, "owner_id": 1, "status": "alive"},
            {"id": 11, "alias": "Luna", "type_id": 1, "owner_id": 1, "status": "alive"},
        ])
    )
    # Invoice for Rex on the visit day
    respx.get(f"{BASE}/rest/api/invoice").mock(
        side_effect=[
            _invoice_response([
                {"id": 100, "pet_id": 10, "invoice_date": "2024-12-15 15:00:00"}
            ]),
            _invoice_response([]),  # Luna: no invoice
        ]
    )
    # Luna fallback to medcard — also nothing
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=_medcards_response([])
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {})

    data = json.loads(result.content[0].text)
    assert len(data["inactive_pets"]) == 1
    pet = data["inactive_pets"][0]
    assert pet["id"] == 10
    assert pet["alias"] == "Rex"
    assert pet["owner_id"] == 1
    assert pet["visit_source"] == "invoice"
    assert pet["last_visit_date"] == "2024-12-15 14:30:00"


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_falls_back_to_medcard_when_no_invoice():
    """When invoice is missing for a pet, medcard is used as fallback."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 2,
                "last_name": "Smith",
                "first_name": "Anna",
                "middle_name": "",
                "cell_phone": "+2000",
                "last_visit_date": "2024-10-01 09:00:00",
            }
        ])
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 20, "alias": "Buddy", "type_id": 1, "owner_id": 2, "status": "alive"},
        ])
    )
    # No invoices
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    # But there is a medcard
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=_medcards_response([
            {"id": 200, "patient_id": 20, "date_create": "2024-10-01 09:30:00"}
        ])
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {})

    data = json.loads(result.content[0].text)
    assert len(data["inactive_pets"]) == 1
    assert data["inactive_pets"][0]["visit_source"] == "medcard"


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_excludes_pets_not_at_last_visit():
    """Pet without invoice or medcard for the visit date is excluded."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 3,
                "last_name": "Brown",
                "first_name": "Bob",
                "middle_name": "",
                "cell_phone": "+3000",
                "last_visit_date": "2024-08-15 10:00:00",
            }
        ])
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 30, "alias": "Ghost", "type_id": 1, "owner_id": 3, "status": "alive"},
        ])
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {})

    data = json.loads(result.content[0].text)
    assert data["inactive_pets"] == []


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_filters_alive_status_only():
    """Only alive pets are queried (status=alive in filter)."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 4,
                "last_name": "Test",
                "first_name": "T",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-01 10:00:00",
            }
        ])
    )
    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(return_value=_pet_response([]))
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_pets", {})

    request = pet_route.calls.last.request
    filter_param = request.url.params.get("filter", "")
    assert '"alive"' in filter_param


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_filters_by_owner_id_not_client_id():
    """Pet filter must use owner_id (not client_id) when fetching pets per client."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 5,
                "last_name": "X",
                "first_name": "Y",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-01 10:00:00",
            }
        ])
    )
    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(return_value=_pet_response([]))
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_pets", {})

    request = pet_route.calls.last.request
    filter_param = request.url.params.get("filter", "")
    assert '"owner_id"' in filter_param
    assert '"client_id"' not in filter_param


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_default_metadata():
    """Default response includes window, months, limit metadata."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {})

    data = json.loads(result.content[0].text)
    assert data["months_min"] == 13
    assert data["months_max"] == 24
    assert data["limit_applied"] == 50
    assert "cutoff_window" in data
    assert "clients_scanned" in data


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_invoice_filter_uses_strict_day_window():
    """Invoice filter must include both >= start_of_day AND < next_day_midnight."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 7,
                "last_name": "X",
                "first_name": "Y",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-15 14:30:00",
            }
        ])
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 70, "alias": "P", "type_id": 1, "owner_id": 7, "status": "alive"}
        ])
    )
    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_pets", {})

    request = invoice_route.calls.last.request
    filter_param = request.url.params.get("filter", "")
    # Both bounds for the same day
    assert "2024-09-15 00:00:00" in filter_param
    assert "2024-09-16 00:00:00" in filter_param
    assert '">="' in filter_param
    assert '"<"' in filter_param


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_paginates_clients_until_limit_reached():
    """When first page has few visited pets, scan additional pages to reach limit."""
    billing_mock()

    # Page 1: 100 clients, only 1 with visited pet (others have no pets/no visits)
    page1_clients = [
        {
            "id": 1000 + i,
            "last_name": f"C{i}",
            "first_name": "X",
            "middle_name": "",
            "cell_phone": "",
            "last_visit_date": "2024-09-15 10:00:00",
        }
        for i in range(100)
    ]
    # Page 2: 5 more clients, all with visited pets
    page2_clients = [
        {
            "id": 2000 + i,
            "last_name": f"D{i}",
            "first_name": "Y",
            "middle_name": "",
            "cell_phone": "",
            "last_visit_date": "2024-09-15 10:00:00",
        }
        for i in range(5)
    ]

    # respx returns sequence: page1 then page2 then empty
    respx.get(f"{BASE}/rest/api/client").mock(
        side_effect=[
            _client_response(page1_clients),
            _client_response(page2_clients),
        ]
    )

    # All page1 clients have NO pets (force underfill)
    # All page2 clients have 1 pet each with invoice
    pet_responses = []
    invoice_responses = []
    for _ in page1_clients:
        pet_responses.append(_pet_response([]))
    for client in page2_clients:
        cid = client["id"]
        pet_responses.append(_pet_response([
            {"id": cid * 10, "alias": f"Pet{cid}", "type_id": 1, "owner_id": cid, "status": "alive"}
        ]))
        invoice_responses.append(_invoice_response([
            {"id": cid * 100, "pet_id": cid * 10, "invoice_date": "2024-09-15 12:00:00"}
        ]))

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_responses)
    respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_responses)
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"limit": 5})

    data = json.loads(result.content[0].text)
    # Pagination: did not give up after page 1, returned all 5 from page 2
    assert len(data["inactive_pets"]) == 5
    assert data["clients_scanned"] >= 100


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_normalizes_last_visit_to_midnight_for_invoice_filter():
    """Invoice filter must use last_visit_date with time 00:00:00, not the original time."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 6,
                "last_name": "X",
                "first_name": "Y",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-15 14:30:00",
            }
        ])
    )
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 60, "alias": "P", "type_id": 1, "owner_id": 6, "status": "alive"}
        ])
    )
    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_pets", {})

    request = invoice_route.calls.last.request
    filter_param = request.url.params.get("filter", "")
    assert "2024-09-15 00:00:00" in filter_param
    assert "14:30:00" not in filter_param
