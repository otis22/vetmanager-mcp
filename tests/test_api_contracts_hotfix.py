"""Regression tests for Stage 86 — fixing create_admission payload contract
and get_medical_cards_by_client_id pet filter (owner_id) + IN-batch.

Context: baseline super-review 2026-04-17 found that:
- create_admission sent payload with {pet_id, client_id, doctor_id, date, status}
  but the Vetmanager admission entity expects
  {patient_id, client_id, user_id, admission_date, status}. Default status
  was 'assigned' which is not in the enum — silently dropped by API.
- get_medical_cards_by_client_id filtered pets by {property: client_id} but
  Pet FK since stage 77.4 is owner_id. Medical cards fetched in N+1 loop
  over pets instead of a single batched IN-query.

These tests pin the fixed contract and prevent regression.
"""

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

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


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


def _filter_of(route) -> list[dict]:
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    return json.loads(q["filter"][0]) if "filter" in q else []


def _query_of(route) -> dict[str, list[str]]:
    url = str(route.calls.last.request.url)
    return parse_qs(urlparse(url).query)


# ── create/update mutation contract gates ───────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_client_maps_fields_to_api_contract():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(201, json={"data": {"id": 101}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_client",
            {
                "first_name": "Ivan",
                "last_name": "Petrov",
                "phone": "+79991234567",
                "email": "ivan@example.invalid",
            },
        )

    body = _body_of(route)
    assert body == {
        "first_name": "Ivan",
        "last_name": "Petrov",
        "cell_phone": "+79991234567",
        "email": "ivan@example.invalid",
    }
    assert "phone" not in body
    assert "firstName" not in body
    assert "lastName" not in body


@pytest.mark.asyncio
async def test_create_payment_is_not_registered_as_mcp_tool():
    tools = await mcp.list_tools()
    assert "create_payment" not in {tool.name for tool in tools}


@pytest.mark.asyncio
@respx.mock
async def test_add_invoice_document_maps_fields_to_api_contract():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(201, json={"data": {"id": 103}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "add_invoice_document",
            {
                "invoice_id": 10,
                "good_id": 20,
                "quantity": 2.0,
                "price": 500.0,
            },
        )

    body = _body_of(route)
    assert body == {
        "invoice_id": 10,
        "good_id": 20,
        "quantity": 2.0,
        "price": 500.0,
    }
    assert "invoiceId" not in body
    assert "goodId" not in body


@pytest.mark.asyncio
@respx.mock
async def test_create_hospitalization_maps_fields_to_api_contract():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/hospital").mock(
        return_value=httpx.Response(201, json={"data": {"id": 104}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_hospitalization",
            {
                "pet_id": 5,
                "doctor_id": 3,
                "date_in": "2026-04-20T10:00:00",
                "block_id": 7,
                "description": "overnight stay",
            },
        )

    body = _body_of(route)
    assert body == {
        "patient_id": 5,
        "doctor_id": 3,
        "date_in": "2026-04-20 10:00:00",
        "hospital_block_id": 7,
        "description": "overnight stay",
    }
    assert "pet_id" not in body
    assert "block_id" not in body


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card_maps_fields_to_api_contract():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(201, json={"data": {"id": 105}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_medical_card",
            {
                "patient_id": 5,
                "doctor_id": 3,
                "date_create": "2026-04-20",
                "description": "Checkup",
                "diagnosis": "Healthy",
                "treatment": "None",
                "recomendation": "Observe",
                "weight": 4.2,
            },
        )

    body = _body_of(route)
    assert body == {
        "patient_id": 5,
        "doctor_id": 3,
        "date_create": "2026-04-20",
        "description": "Checkup",
        "diagnos": "Healthy",
        "treatment": "None",
        "recomendation": "Observe",
        "weight": 4.2,
    }
    assert "diagnosis" not in body


@pytest.mark.asyncio
@respx.mock
async def test_update_medical_card_maps_fields_to_api_contract():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_medical_card",
            {
                "card_id": 42,
                "description": "Updated",
                "diagnosis": "Recovered",
                "temperature": 38.5,
            },
        )

    body = _body_of(route)
    assert body == {
        "description": "Updated",
        "diagnos": "Recovered",
        "temperature": 38.5,
    }
    assert "diagnosis" not in body


# ── create_admission ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_maps_fields_to_api_contract():
    """create_admission must translate external names (pet_id/doctor_id/date)
    to API field names (patient_id/user_id/admission_date)."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_admission",
            {
                "pet_id": 5,
                "client_id": 1,
                "doctor_id": 3,
                "date": "2026-04-20T10:00:00",
                "reason": "checkup",
            },
        )

    assert route.call_count == 1
    body = _body_of(route)
    # Correct API field names
    assert body["patient_id"] == 5
    assert body["client_id"] == 1
    assert body["user_id"] == 3
    assert body["admission_date"] == "2026-04-20 10:00:00"
    assert body["reason"] == "checkup"
    # Must NOT leak external names into the API payload
    assert "pet_id" not in body
    assert "doctor_id" not in body
    assert "date" not in body


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_default_status_is_save():
    """Default status must be a valid enum value ('save'), not the invented
    'assigned' that VM silently drops."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_admission",
            {
                "pet_id": 5,
                "client_id": 1,
                "doctor_id": 3,
                "date": "2026-04-20T10:00:00",
            },
        )

    body = _body_of(route)
    assert body["status"] == "save"


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_passes_explicit_status_through():
    """Explicit status param (valid enum) passes through unchanged."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 8}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_admission",
            {
                "pet_id": 5,
                "client_id": 1,
                "doctor_id": 3,
                "date": "2026-04-20T10:00:00",
                "status": "not_confirmed",
            },
        )

    body = _body_of(route)
    assert body["status"] == "not_confirmed"


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_invalid_status_rejected():
    """Tool layer should reject invented enum values before any HTTP call."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 999}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="invalid admission status"):
            await mcp.call_tool(
                "create_admission",
                {
                    "pet_id": 5,
                    "client_id": 1,
                    "doctor_id": 3,
                    "date": "2026-04-20T10:00:00",
                    "status": "assigned",
                },
            )

    assert route.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_normalizes_vm_datetime_edge_cases():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        for value in (
            "2026-04-20T10:15",
            "2026-04-20T10:15:30.987654",
            "2026-04-20 10:15:30",
        ):
            await mcp.call_tool(
                "create_admission",
                {
                    "pet_id": 5,
                    "client_id": 1,
                    "doctor_id": 3,
                    "date": value,
                },
            )

    assert json.loads(route.calls[0].request.content)["admission_date"] == "2026-04-20 10:15:00"
    assert json.loads(route.calls[1].request.content)["admission_date"] == "2026-04-20 10:15:30"
    assert json.loads(route.calls[2].request.content)["admission_date"] == "2026-04-20 10:15:30"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "bad_date",
    [
        "2026-04-20",
        "2026-04-20 10:15",
        "2026-04-20T10:15:00Z",
        "2026-04-20T10:15:00+03:00",
        "not-a-date",
    ],
)
async def test_create_admission_rejects_invalid_vm_datetime_before_http(bad_date):
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="invalid VM datetime"):
            await mcp.call_tool(
                "create_admission",
                {
                    "pet_id": 5,
                    "client_id": 1,
                    "doctor_id": 3,
                    "date": bad_date,
                },
            )

    assert route.call_count == 0


# ── get_medical_cards_by_client_id ──────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_filters_pets_by_owner_id():
    """Step 1 must filter pets by owner_id (not legacy client_id)."""
    billing_mock()
    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"pet": [{"id": 7, "alias": "Barney", "owner_id": 42}]}},
        )
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "medicalCards": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_medical_cards_by_client_id", {"client_id": 42})

    filters = _filter_of(pet_route)
    assert any(
        f.get("property") == "owner_id" and str(f.get("value")) == "42"
        for f in filters
    ), f"expected owner_id=42 filter, got {filters}"
    # And must NOT send legacy client_id filter on pet
    assert not any(f.get("property") == "client_id" for f in filters)


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_batches_medcards_via_in_operator():
    """Step 2 must fetch medical cards for all pets in ONE request using
    patient_id IN [...], not N sequential calls."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "pet": [
                        {"id": 1, "alias": "A", "owner_id": 42},
                        {"id": 2, "alias": "B", "owner_id": 42},
                        {"id": 3, "alias": "C", "owner_id": 42},
                    ]
                }
            },
        )
    )
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 4,
                    "medicalCards": [
                        {"id": 100, "patient_id": 1, "description": "A1"},
                        {"id": 101, "patient_id": 1, "description": "A2"},
                        {"id": 102, "patient_id": 2, "description": "B1"},
                        {"id": 103, "patient_id": 3, "description": "C1"},
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_medical_cards_by_client_id", {"client_id": 42}
        )

    # N+1 regression: exactly ONE medcard call, not 3.
    assert medcard_route.call_count == 1, (
        f"expected 1 batched medcard call, got {medcard_route.call_count}"
    )

    filters = _filter_of(medcard_route)
    in_filter = next(
        (f for f in filters if f.get("property") == "patient_id"), None
    )
    assert in_filter is not None, f"no patient_id filter: {filters}"
    assert in_filter.get("operator", "").lower() == "in", (
        f"expected IN operator, got {in_filter}"
    )
    # Stage 101.4: pin canonical int-typed wire format. VM API expects
    # integer IDs in IN-list; string-form may silently fail server-side.
    assert sorted(in_filter.get("value", [])) == [1, 2, 3]

    structured = result.structured_content or {}
    assert structured.get("pets_count") == 3
    assert structured.get("medical_cards_count") == 4


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_no_pets_short_circuits():
    """If client has no pets, must return empty result without hitting MedicalCards."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": {"pet": []}})
    )
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"medicalCards": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_medical_cards_by_client_id", {"client_id": 999}
        )

    assert medcard_route.call_count == 0
    structured = result.structured_content or {}
    assert structured.get("pets_count") == 0
    assert structured.get("medical_cards") == []


# ── Stage 122 payload/query contract hotfixes ───────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_create_hospitalization_maps_payload_to_snake_case():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/hospital").mock(
        return_value=httpx.Response(201, json={"data": {"id": 20}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_hospitalization",
            {
                "pet_id": 5,
                "doctor_id": 3,
                "date_in": "2026-04-21T09:00:00",
                "block_id": 2,
                "description": "ICU",
            },
        )

    body = _body_of(route)
    assert body["patient_id"] == 5
    assert body["doctor_id"] == 3
    assert body["date_in"] == "2026-04-21 09:00:00"
    assert body["hospital_block_id"] == 2
    assert body["description"] == "ICU"
    assert "petId" not in body
    assert "doctorId" not in body
    assert "dateIn" not in body
    assert "blockId" not in body


@pytest.mark.asyncio
@respx.mock
async def test_update_hospitalization_maps_payload_to_snake_case():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/hospital/3").mock(
        return_value=httpx.Response(200, json={"data": {"id": 3}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_hospitalization",
            {
                "hospital_id": 3,
                "date_out": "2026-04-22T10:00:00",
                "block_id": 4,
                "status": "closed",
            },
        )

    body = _body_of(route)
    assert body["date_out"] == "2026-04-22 10:00:00"
    assert body["hospital_block_id"] == 4
    assert body["status"] == "closed"
    assert "dateOut" not in body
    assert "blockId" not in body


@pytest.mark.asyncio
@respx.mock
async def test_update_hospitalization_empty_date_out_is_omitted():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/hospital/3").mock(
        return_value=httpx.Response(200, json={"data": {"id": 3}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_hospitalization",
            {
                "hospital_id": 3,
                "date_out": "",
                "status": "open",
            },
        )

    assert _body_of(route) == {"status": "open"}


@pytest.mark.asyncio
@respx.mock
async def test_get_payments_uses_client_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_payments", {"client_id": 42, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "client_id" and f.get("value") == 42
        for f in filters
    ), f"expected client_id filter, got {filters}"
    assert "clientId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_payments_uses_create_date_filters_for_march_2026_revenue():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "payment": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_payments",
            {"date_from": "2026-03-01", "date_to": "2026-03-31", "limit": 100},
        )

    filters = _filter_of(route)
    by_operator = {
        f.get("operator"): f.get("value")
        for f in filters
        if f.get("property") == "create_date"
    }
    assert by_operator[">="] == "2026-03-01"
    assert by_operator["<="] == "2026-03-31"


@pytest.mark.asyncio
@respx.mock
async def test_get_payments_date_filters_merge_with_client_and_caller_filters():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "payment": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_payments",
            {
                "client_id": 42,
                "date_from": "2026-03-01",
                "filter": [
                    {"property": "payment_type", "operator": "=", "value": "cash"}
                ],
                "limit": 20,
            },
        )

    filters = _filter_of(route)
    assert any(f.get("property") == "client_id" and f.get("value") == 42 for f in filters)
    assert any(
        f.get("property") == "create_date"
        and f.get("operator") == ">="
        and f.get("value") == "2026-03-01"
        for f in filters
    )
    assert any(
        f.get("property") == "payment_type"
        and f.get("operator") == "="
        and f.get("value") == "cash"
        for f in filters
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_invoices_uses_client_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "invoice": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_invoices", {"client_id": 42, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "client_id" and f.get("value") == 42
        for f in filters
    ), f"expected client_id filter, got {filters}"
    assert "client_id" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_add_invoice_document_maps_payload_to_snake_case():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(201, json={"data": {"id": 99}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "add_invoice_document",
            {"invoice_id": 50, "good_id": 2, "quantity": 1, "price": 250.0},
        )

    body = _body_of(route)
    assert body["invoice_id"] == 50
    assert body["good_id"] == 2
    assert body["quantity"] == 1
    assert body["price"] == 250.0
    assert "invoiceId" not in body
    assert "goodId" not in body


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice_documents_uses_invoice_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_invoice_documents", {"invoice_id": 50, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "invoice_id" and f.get("value") == 50
        for f in filters
    ), f"expected invoice_id filter, got {filters}"
    assert "invoiceId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_create_client_maps_payload_to_snake_case():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(201, json={"data": {"id": 99}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_client",
            {
                "first_name": "Eve",
                "last_name": "Smith",
                "phone": "+7 999 123-45-67",
                "email": "eve@example.com",
            },
        )

    body = _body_of(route)
    assert body["first_name"] == "Eve"
    assert body["last_name"] == "Smith"
    assert body["cell_phone"] == "+7 999 123-45-67"
    assert body["email"] == "eve@example.com"
    assert "firstName" not in body
    assert "lastName" not in body
    assert "phone" not in body


@pytest.mark.asyncio
@respx.mock
async def test_get_breeds_uses_pet_type_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/breed").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_breeds", {"pet_type_id": 7, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "pet_type_id" and f.get("value") == 7
        for f in filters
    ), f"expected pet_type_id filter, got {filters}"
    assert "petTypeId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_good_sale_params_uses_good_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "goodSaleParam": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_good_sale_params", {"good_id": 7, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "good_id" and f.get("value") == 7
        for f in filters
    ), f"expected good_id filter, got {filters}"
    assert "goodId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_cities_uses_title_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/city").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "city": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_cities", {"title": "Москва", "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "title" and f.get("value") == "%Москва%"
        and f.get("operator") == "LIKE"
        for f in filters
    ), f"expected title LIKE filter, got {filters}"
    assert "title" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_streets_uses_city_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/street").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "street": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_streets", {"city_id": 5, "limit": 20})

    filters = _filter_of(route)
    assert any(
        f.get("property") == "city_id" and f.get("value") == 5
        for f in filters
    ), f"expected city_id filter, got {filters}"
    assert "cityId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_combo_manual_items_uses_name_id_filter_not_legacy_query_param():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/ComboManualItem").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "comboManualItem": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_combo_manual_items",
            {"combo_manual_name_id": 9, "limit": 20},
        )

    filters = _filter_of(route)
    assert any(
        f.get("property") == "combo_manual_name_id" and f.get("value") == 9
        for f in filters
    ), f"expected combo_manual_name_id filter, got {filters}"
    assert "comboManualNameId" not in _query_of(route)


@pytest.mark.asyncio
@respx.mock
async def test_get_vaccinations_reports_truncation_metadata():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "medicalcards": [
                        {"id": 1, "name": "A", "pet_id": 66},
                        {"id": 2, "name": "B", "pet_id": 66},
                        {"id": 3, "name": "C", "pet_id": 66},
                    ],
                    "totalCount": 3,
                },
                "success": True,
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_vaccinations", {"pet_id": 66, "limit": 2})

    data = result.structured_content
    assert data["returnedCount"] == 2
    assert data["totalCount"] == 3
    assert data["truncated"] is True
    assert [row["id"] for row in data["vaccinations"]] == [1, 2]
    assert _query_of(route)["pet_id"] == ["66"]


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_paginates_owner_pets():
    billing_mock()
    pet_requests: list[dict[str, list[str]]] = []
    card_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "medicalCards": []}})
    )

    def _pet_response(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        pet_requests.append(query)
        offset = int(query.get("offset", ["0"])[0])
        pets = [{"id": 101, "alias": "A"}] if offset == 0 else [{"id": 202, "alias": "B"}]
        return httpx.Response(
            200,
            json={"data": {"totalCount": 2, "pet": pets}},
        )

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=_pet_response)
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_medical_cards_by_client_id",
            {"client_id": 42, "limit": 20},
        )

    assert [request["offset"][0] for request in pet_requests] == ["0", "100"]
    assert result.structured_content["pets_count"] == 2
    assert result.structured_content["pets_total"] == 2
    assert result.structured_content["pets_truncated"] is False
    card_filters = _filter_of(card_route)
    patient_filter = next(f for f in card_filters if f.get("property") == "patient_id")
    assert patient_filter["operator"].upper() == "IN"
    assert patient_filter["value"] == [101, 202]


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_marks_truncated_on_empty_pet_page_before_total():
    billing_mock()
    pet_requests: list[dict[str, list[str]]] = []

    def _pet_response(request: httpx.Request) -> httpx.Response:
        query = parse_qs(urlparse(str(request.url)).query)
        pet_requests.append(query)
        offset = int(query.get("offset", ["0"])[0])
        pets = [{"id": 101, "alias": "A"}] if offset == 0 else []
        return httpx.Response(
            200,
            json={"data": {"totalCount": 300, "pet": pets}},
        )

    respx.get(f"{BASE}/rest/api/pet").mock(side_effect=_pet_response)
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "medicalCards": []}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_medical_cards_by_client_id",
            {"client_id": 42, "limit": 20},
        )

    assert [request["offset"][0] for request in pet_requests] == ["0", "100"]
    assert result.structured_content["pets_count"] == 1
    assert result.structured_content["pets_total"] == 300
    assert result.structured_content["pets_truncated"] is True


@pytest.mark.asyncio
@respx.mock
async def test_create_timesheet_normalizes_datetime_payload():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 77}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_timesheet",
            {
                "doctor_id": 7,
                "begin_datetime": "2026-04-24T09:30:15.123",
                "end_datetime": "2026-04-24 18:00:00",
                "clinic_id": 2,
            },
        )

    body = _body_of(route)
    assert body["begin_datetime"] == "2026-04-24 09:30:15"
    assert body["end_datetime"] == "2026-04-24 18:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_create_timesheet_rejects_timezone_datetime_before_http():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 77}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "create_timesheet",
                {
                    "doctor_id": 7,
                    "begin_datetime": "2026-04-24T09:30:00+03:00",
                    "end_datetime": "2026-04-24T18:00:00",
                    "clinic_id": 2,
                },
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("date", "expected_begin_upper", "expected_end_lower"),
    [
        ("2026-04-21", "2026-04-22 00:00:00", "2026-04-21 00:00:00"),
        ("2026-04-22", "2026-04-23 00:00:00", "2026-04-22 00:00:00"),
    ],
)
async def test_get_timesheets_maps_date_to_overlap_datetime_filters(
    date: str,
    expected_begin_upper: str,
    expected_end_lower: str,
):
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_timesheets",
            {"doctor_id": 7, "date": date, "limit": 20},
        )

    filters = _filter_of(route)
    assert any(
        f.get("property") == "doctor_id" and f.get("value") == 7
        for f in filters
    ), f"expected doctor_id filter, got {filters}"
    assert any(
        f.get("property") == "begin_datetime"
        and f.get("operator") == "<"
        and f.get("value") == expected_begin_upper
        for f in filters
    ), f"expected begin_datetime overlap upper bound, got {filters}"
    assert any(
        f.get("property") == "end_datetime"
        and f.get("operator") == ">"
        and f.get("value") == expected_end_lower
        for f in filters
    ), f"expected end_datetime overlap lower bound, got {filters}"
    assert "date" not in _query_of(route)
