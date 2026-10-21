"""Stage 429: client medical-card pages must disclose remaining records."""

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


BASE = "https://testclinic.vetmanager.cloud"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("offset", "total", "cards", "expected_total", "has_more"),
    [
        (0, 3, [{"id": 10, "patient_id": 7}], 3, True),
        (2, "3", [{"id": 12, "patient_id": 7}], 3, False),
        (1, 3, [], 3, None),
        (0, None, [{"id": 10, "patient_id": 7}], None, None),
        (0, -1, [{"id": 10, "patient_id": 7}], None, None),
        (0, True, [{"id": 10, "patient_id": 7}], None, None),
        (0, "٣", [{"id": 10, "patient_id": 7}], None, None),
    ],
)
@respx.mock
async def test_client_card_page_discloses_total_and_remaining(
    offset, total, cards, expected_total, has_more,
):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/pet").mock(return_value=httpx.Response(
        200, json={"data": {"pet": [{"id": 7, "alias": "A"}], "totalCount": 1}},
    ))
    data = {"medicalCards": cards}
    if total is not None:
        data["totalCount"] = total
    route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": data})
    )
    headers_patch, runtime_patch = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers_patch, runtime_patch:
        response = await mcp.call_tool("get_medical_cards_by_client_id", {
            "client_id": 42, "limit": 1, "offset": offset,
        })
    body = response.structured_content
    assert response.is_error is False
    assert route.call_count == 1
    assert route.calls.last.request.url.params["offset"] == str(offset)
    assert body["medical_cards_count"] == len(cards)
    assert body["medical_cards_total"] == expected_total
    assert body["medical_cards_has_more"] is has_more
    assert body["pets_truncated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_client_card_page_without_pets_is_complete():
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.get(f"{BASE}/rest/api/pet").mock(return_value=httpx.Response(
        200, json={"data": {"pet": [], "totalCount": 0}},
    ))
    headers_patch, runtime_patch = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers_patch, runtime_patch:
        response = await mcp.call_tool("get_medical_cards_by_client_id", {"client_id": 42})
    body = response.structured_content
    assert body["medical_cards_total"] == 0
    assert body["medical_cards_has_more"] is False
