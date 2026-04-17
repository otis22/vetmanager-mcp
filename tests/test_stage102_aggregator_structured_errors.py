"""Stage 102.7 + 103.7 regressions: aggregators use gather_sections with
structured section_errors shape {error_type, retryable, message}.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest
import respx

from exceptions import VetmanagerUpstreamUnavailable
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
        DOMAIN, API_KEY, bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_client_profile_section_errors_have_structured_shape():
    billing_mock()
    # invoice section returns 5xx → partial failure, classified as vetmanager_error
    respx.get(f"{BASE}/rest/api/client/7").mock(
        return_value=httpx.Response(200, json={"data": {"client": {"id": 7}}})
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"admission": []}})
    )

    async def _no_sleep(_):
        return None
    import vetmanager_client as vm
    original_sleep = vm.asyncio.sleep
    vm.asyncio.sleep = _no_sleep
    try:
        headers_patch, runtime_patch = bearer_runtime_patch()
        with headers_patch, runtime_patch:
            result = await mcp.call_tool("get_client_profile", {"client_id": 7})
    finally:
        vm.asyncio.sleep = original_sleep

    structured = result.structured_content or {}
    assert structured.get("partial") is True
    errors = structured.get("section_errors", {})
    assert "invoices" in errors
    inv_err = errors["invoices"]
    assert isinstance(inv_err, dict), f"expected dict shape, got {inv_err!r}"
    assert "error_type" in inv_err
    assert "retryable" in inv_err
    assert "message" in inv_err
    # 5xx → VetmanagerError → retryable=True
    assert inv_err["error_type"] == "vetmanager_error"
    assert inv_err["retryable"] is True


@pytest.mark.asyncio
@respx.mock
async def test_get_pet_profile_section_errors_have_structured_shape():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/5").mock(
        return_value=httpx.Response(200, json={"data": {"pet": {"id": 5, "alias": "Rex"}}})
    )
    # vaccinations returns 404 → NotFoundError → retryable=False
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"data": {"medicalCards": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(404)
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_pet_profile", {"pet_id": 5})

    structured = result.structured_content or {}
    assert structured.get("partial") is True
    errors = structured.get("section_errors", {})
    assert "vaccinations" in errors
    vacc_err = errors["vaccinations"]
    assert vacc_err["error_type"] == "not_found"
    assert vacc_err["retryable"] is False
