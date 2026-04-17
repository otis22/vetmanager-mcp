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
    assert body["admission_date"] == "2026-04-20T10:00:00"
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
