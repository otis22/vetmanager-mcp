"""Tests for get_inactive_pets tool — per-pet visit detection algorithm."""

from urllib.parse import parse_qs, urlparse
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
    import json as _json
    filter_list = _json.loads(filter_param)
    status_filter = next(
        (f for f in filter_list if f.get("property") == "status"), None
    )
    assert status_filter is not None, (
        f"expected status filter on pet, got {filter_list}"
    )
    assert status_filter["value"] == "alive"


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
    import json as _json
    filter_list = _json.loads(filter_param)
    owner_filter = next(
        (f for f in filter_list if f.get("property") == "owner_id"), None
    )
    assert owner_filter is not None, (
        f"expected owner_id filter, got {filter_list}"
    )
    client_id_filter = next(
        (f for f in filter_list if f.get("property") == "client_id"), None
    )
    assert client_id_filter is None, (
        f"pet filter must not use legacy client_id property: {filter_list}"
    )


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
async def test_get_inactive_pets_batches_invoice_and_medcard_via_in_operator():
    """Stage 83: a client with 5 pets must trigger exactly 1 invoice call
    (IN operator), and at most 1 medcard call for pets missing invoices."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 8,
                "last_name": "Batch",
                "first_name": "Test",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-10 10:00:00",
            }
        ])
    )
    # 5 alive pets for this client
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=_pet_response([
            {"id": 800 + i, "alias": f"P{i}", "owner_id": 8, "status": "alive"}
            for i in range(5)
        ])
    )
    # One batched invoice response containing records for pets 800 and 801 only
    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=_invoice_response([
            {"id": 1, "pet_id": 800, "invoice_date": "2024-09-10 11:00:00"},
            {"id": 2, "pet_id": 801, "invoice_date": "2024-09-10 12:00:00"},
        ])
    )
    # One batched medcard response for remaining pets — returns card for pet 802
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=_medcards_response([
            {"id": 500, "patient_id": 802, "date_create": "2024-09-10 13:00:00"},
        ])
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {})

    # Exactly 1 invoice call + 1 medcard call (batching via IN).
    assert invoice_route.call_count == 1
    assert medcard_route.call_count == 1

    # Invoice filter must use IN operator with a list of pet_ids.
    inv_filter = invoice_route.calls.last.request.url.params.get("filter", "")
    assert '"IN"' in inv_filter
    assert '"pet_id"' in inv_filter

    # Medcard filter must use IN on patient_id only for pets 802, 803, 804
    # (pets 800, 801 already matched via invoices).
    mc_filter = medcard_route.calls.last.request.url.params.get("filter", "")
    assert '"IN"' in mc_filter
    assert '"patient_id"' in mc_filter
    assert "802" in mc_filter
    assert "803" in mc_filter
    assert "804" in mc_filter
    # 800 and 801 should NOT be in the remaining list
    mc_filter_data = json.loads(mc_filter)
    patient_in = next(f for f in mc_filter_data if f["property"] == "patient_id")
    assert 800 not in patient_in["value"]
    assert 801 not in patient_in["value"]

    # Result: pets 800, 801 (invoice), 802 (medcard) = 3 visited
    data = json.loads(result.content[0].text)
    assert len(data["inactive_pets"]) == 3
    sources = {p["id"]: p["visit_source"] for p in data["inactive_pets"]}
    assert sources[800] == "invoice"
    assert sources[801] == "invoice"
    assert sources[802] == "medcard"


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

    # Batched path:
    # page 1 owner batch -> no pets, page 2 owner batch -> 5 pets, one invoice batch.
    respx.get(f"{BASE}/rest/api/pet").mock(
        side_effect=[
            _pet_response([]),
            _pet_response([
                {
                    "id": client["id"] * 10,
                    "alias": f"Pet{client['id']}",
                    "type_id": 1,
                    "owner_id": client["id"],
                    "status": "alive",
                }
                for client in page2_clients
            ]),
        ]
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=_invoice_response([
            {
                "id": client["id"] * 100,
                "pet_id": client["id"] * 10,
                "invoice_date": "2024-09-15 12:00:00",
            }
            for client in page2_clients
        ])
    )
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


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_batches_lookup_for_large_client_page():
    """A 100-client page should not trigger client-by-client pet/invoice requests."""
    billing_mock()

    clients = [
        {
            "id": 3000 + i,
            "last_name": f"C{i}",
            "first_name": "Batch",
            "middle_name": "",
            "cell_phone": "",
            "last_visit_date": "2024-09-15 10:00:00",
        }
        for i in range(100)
    ]
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"totalCount": 2000, "client": clients}},
        )
    )

    pets_by_owner = {
        client["id"]: {
            "id": client["id"] * 10,
            "alias": f"Pet{client['id']}",
            "owner_id": client["id"],
            "status": "alive",
        }
        for client in clients
    }

    def pet_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        filters = json.loads(q["filter"][0])
        owner_filter = next(f for f in filters if f["property"] == "owner_id")
        value = owner_filter["value"]
        owner_ids = value if isinstance(value, list) else [value]
        pets = [pets_by_owner[int(owner_id)] for owner_id in owner_ids if int(owner_id) in pets_by_owner]
        return _pet_response(pets)

    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_side_effect)

    invoices_by_pet = {
        pet["id"]: {
            "id": pet["id"] * 100,
            "pet_id": pet["id"],
            "invoice_date": "2024-09-15 12:00:00",
        }
        for pet in list(pets_by_owner.values())[:50]
    }

    def invoice_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        filters = json.loads(q["filter"][0])
        pet_filter = next(f for f in filters if f["property"] == "pet_id")
        value = pet_filter["value"]
        pet_ids = value if isinstance(value, list) else [value]
        invoices = [
            invoices_by_pet[int(pet_id)]
            for pet_id in pet_ids
            if int(pet_id) in invoices_by_pet
        ]
        return _invoice_response(invoices)

    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_side_effect)
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"limit": 50})

    data = json.loads(result.content[0].text)
    assert len(data["inactive_pets"]) == 50
    assert pet_route.call_count < 30
    assert invoice_route.call_count < 30
    assert medcard_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_fetches_pets_beyond_first_100_owner_records():
    """A client with >100 pets must be scanned across pet/invoice chunks."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 99,
                "last_name": "Large",
                "first_name": "Owner",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-15 10:00:00",
            }
        ])
    )

    all_pets = [
        {"id": idx, "alias": f"P{idx}", "type_id": 1, "owner_id": 99, "status": "alive"}
        for idx in range(1, 206)
    ]

    def pet_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["100"])[0])
        page = all_pets[offset:offset + limit]
        return _pet_response(page)

    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_side_effect)

    visited_ids = {201, 202, 203, 204, 205}

    def invoice_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        filters = json.loads(q["filter"][0])
        pet_filter = next(f for f in filters if f["property"] == "pet_id")
        pet_ids = pet_filter["value"]
        invoices = [
            {"id": pet_id * 100, "pet_id": pet_id, "invoice_date": "2024-09-15 12:00:00"}
            for pet_id in pet_ids
            if pet_id in visited_ids
        ]
        return _invoice_response(invoices)

    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_side_effect)
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"limit": 10})

    data = json.loads(result.content[0].text)
    returned_ids = {pet["id"] for pet in data["inactive_pets"]}
    assert visited_ids.issubset(returned_ids)
    assert pet_route.call_count >= 3
    assert invoice_route.call_count >= 3


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_paginates_invoice_chunk_over_100_rows():
    """Invoice chunk pagination must not drop visited pets beyond first 100 rows."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 55,
                "last_name": "Invoice",
                "first_name": "Overflow",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-15 10:00:00",
            }
        ])
    )

    pets = [
        {"id": 1000 + i, "alias": f"P{i}", "type_id": 1, "owner_id": 55, "status": "alive"}
        for i in range(100)
    ]

    def pet_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["100"])[0])
        page = pets[offset:offset + limit]
        return httpx.Response(
            200,
            json={"data": {"totalCount": len(pets), "pet": page}},
        )

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_side_effect)

    overflow_pet_id = pets[-1]["id"]
    invoice_pet_ids = [pet["id"] for pet in pets[:-1]]
    invoice_pet_ids.append(pets[0]["id"])
    invoice_pet_ids.extend([overflow_pet_id] + [pets[1]["id"]] * 49)
    all_invoices = [
        {"id": 2000 + idx, "pet_id": pet_id, "invoice_date": "2024-09-15 12:00:00"}
        for idx, pet_id in enumerate(invoice_pet_ids, start=1)
    ]

    def invoice_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["100"])[0])
        page = all_invoices[offset:offset + limit]
        return httpx.Response(
            200,
            json={"data": {"totalCount": len(all_invoices), "invoice": page}},
        )

    invoice_route = respx.get(f"{BASE}/rest/api/invoice").mock(side_effect=invoice_side_effect)
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(return_value=_medcards_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"limit": 100})

    data = json.loads(result.content[0].text)
    returned_ids = {pet["id"] for pet in data["inactive_pets"]}
    assert len(data["inactive_pets"]) == 100
    assert pets[-1]["id"] in returned_ids
    assert invoice_route.call_count == 2
    assert medcard_route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_pets_paginates_medcard_chunk_over_100_rows():
    """Medcard fallback pagination must not drop visited pets beyond first 100 rows."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=_client_response([
            {
                "id": 56,
                "last_name": "Medcard",
                "first_name": "Overflow",
                "middle_name": "",
                "cell_phone": "",
                "last_visit_date": "2024-09-15 10:00:00",
            }
        ])
    )

    pets = [
        {"id": 3000 + i, "alias": f"M{i}", "type_id": 1, "owner_id": 56, "status": "alive"}
        for i in range(100)
    ]

    def pet_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["100"])[0])
        page = pets[offset:offset + limit]
        return httpx.Response(
            200,
            json={"data": {"totalCount": len(pets), "pet": page}},
        )

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=pet_side_effect)
    respx.get(f"{BASE}/rest/api/invoice").mock(return_value=_invoice_response([]))

    overflow_pet_id = pets[-1]["id"]
    medcard_pet_ids = [pet["id"] for pet in pets[:-1]]
    medcard_pet_ids.append(pets[0]["id"])
    medcard_pet_ids.extend([overflow_pet_id] + [pets[1]["id"]] * 49)
    all_medcards = [
        {"id": 4000 + idx, "patient_id": pet_id, "date_create": "2024-09-15 12:00:00"}
        for idx, pet_id in enumerate(medcard_pet_ids, start=1)
    ]

    def medcard_side_effect(request):
        q = parse_qs(urlparse(str(request.url)).query)
        offset = int(q.get("offset", ["0"])[0])
        limit = int(q.get("limit", ["100"])[0])
        page = all_medcards[offset:offset + limit]
        return httpx.Response(
            200,
            json={"data": {"totalCount": len(all_medcards), "medicalCards": page}},
        )

    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(side_effect=medcard_side_effect)

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_pets", {"limit": 100})

    data = json.loads(result.content[0].text)
    returned_ids = {pet["id"] for pet in data["inactive_pets"]}
    assert len(data["inactive_pets"]) == 100
    assert pets[-1]["id"] in returned_ids
    assert medcard_route.call_count == 2
