"""E2E mock tests: CRUD operations and error scenarios."""

"""E2E mock/contract tests for all MCP tools via respx."""

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


def client(domain=DOMAIN, api_key=API_KEY):
    return make_client_with_resolved_runtime(
        domain,
        api_key,
        bearer_token="mock-token",
    )


def bearer_runtime_patch(domain=DOMAIN, api_key=API_KEY):
    return patch_runtime_credentials(
        domain,
        api_key,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


# ── Client tools ─────────────────────────────────────────────────────────────



# -- UPDATE tools --

@pytest.mark.asyncio
@respx.mock
async def test_update_invoice():
    billing_mock()
    respx.put(f"{BASE}/rest/api/invoice/10").mock(
        return_value=httpx.Response(200, json={"data": {"id": 10, "description": "Updated"}})
    )
    result = await client().put("/rest/api/invoice/10", json={"description": "Updated"})
    assert result["data"]["id"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_update_invoice_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/invoice/10").mock(
        return_value=httpx.Response(200, json={"data": {"id": 10, "description": "Updated"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_invoice", {"invoice_id": 10, "description": "Updated"})
    assert route.called
    assert b'"description"' in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_update_user():
    billing_mock()
    respx.put(f"{BASE}/rest/api/user/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5, "last_name": "Ivanov"}})
    )
    result = await client().put("/rest/api/user/5", json={"last_name": "Ivanov"})
    assert result["data"]["last_name"] == "Ivanov"


@pytest.mark.asyncio
@respx.mock
async def test_update_user_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/user/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5, "last_name": "Ivanov"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_user", {"user_id": 5, "last_name": "Ivanov"})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_update_hospitalization():
    billing_mock()
    respx.put(f"{BASE}/rest/api/hospital/3").mock(
        return_value=httpx.Response(200, json={"data": {"id": 3, "status": "discharged"}})
    )
    result = await client().put("/rest/api/hospital/3", json={"status": "discharged"})
    assert result["data"]["status"] == "discharged"


@pytest.mark.asyncio
@respx.mock
async def test_update_hospitalization_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/hospital/3").mock(
        return_value=httpx.Response(200, json={"data": {"id": 3, "status": "discharged"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_hospitalization", {"hospital_id": 3, "status": "discharged"})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_update_supplier():
    billing_mock()
    respx.put(f"{BASE}/rest/api/Suppliers/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7, "company_name": "NewCo"}})
    )
    result = await client().put("/rest/api/Suppliers/7", json={"company_name": "NewCo"})
    assert result["data"]["company_name"] == "NewCo"


@pytest.mark.asyncio
@respx.mock
async def test_update_supplier_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/Suppliers/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7, "company_name": "NewCo"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_supplier", {"supplier_id": 7, "company_name": "NewCo"})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_update_good():
    billing_mock()
    respx.put(f"{BASE}/rest/api/good/15").mock(
        return_value=httpx.Response(200, json={"data": {"id": 15, "title": "Updated Good"}})
    )
    result = await client().put("/rest/api/good/15", json={"title": "Updated Good"})
    assert result["data"]["title"] == "Updated Good"


@pytest.mark.asyncio
@respx.mock
async def test_update_good_tool():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/good/15").mock(
        return_value=httpx.Response(200, json={"data": {"id": 15, "title": "Updated Good"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_good", {"good_id": 15, "title": "Updated Good"})
    assert route.called


# -- DELETE tools --

@pytest.mark.asyncio
@respx.mock
async def test_delete_client():
    billing_mock()
    respx.delete(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    result = await client().delete("/rest/api/client/42")
    assert result["data"]["id"] == 42


@pytest.mark.asyncio
@respx.mock
async def test_delete_client_tool():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("delete_client", {"client_id": 42})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_delete_pet():
    billing_mock()
    respx.delete(f"{BASE}/rest/api/pet/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5}})
    )
    result = await client().delete("/rest/api/pet/5")
    assert result["data"]["id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_delete_pet_tool():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/pet/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("delete_pet", {"pet_id": 5})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice():
    billing_mock()
    respx.delete(f"{BASE}/rest/api/invoice/10").mock(
        return_value=httpx.Response(200, json={"data": {"id": 10}})
    )
    result = await client().delete("/rest/api/invoice/10")
    assert result["data"]["id"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice_tool():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/invoice/10").mock(
        return_value=httpx.Response(200, json={"data": {"id": 10}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("delete_invoice", {"invoice_id": 10})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice_document():
    billing_mock()
    respx.delete(f"{BASE}/rest/api/invoiceDocument/20").mock(
        return_value=httpx.Response(200, json={"data": {"id": 20}})
    )
    result = await client().delete("/rest/api/invoiceDocument/20")
    assert result["data"]["id"] == 20


@pytest.mark.asyncio
@respx.mock
async def test_delete_invoice_document_tool():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/invoiceDocument/20").mock(
        return_value=httpx.Response(200, json={"data": {"id": 20}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("delete_invoice_document", {"doc_id": 20})
    assert route.called


# -- CREATE tools --

@pytest.mark.asyncio
@respx.mock
async def test_create_good():
    billing_mock()
    respx.post(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(201, json={"data": {"id": 50, "title": "Vaccine X"}})
    )
    result = await client().post("/rest/api/good", json={"title": "Vaccine X"})
    assert result["data"]["title"] == "Vaccine X"


@pytest.mark.asyncio
@respx.mock
async def test_create_good_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(201, json={"data": {"id": 50, "title": "Vaccine X"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("create_good", {"title": "Vaccine X"})
    assert route.called
    assert b'"title":"Vaccine X"' in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_create_supplier():
    billing_mock()
    respx.post(f"{BASE}/rest/api/Suppliers").mock(
        return_value=httpx.Response(201, json={"data": {"id": 30, "company_name": "PharmaVet"}})
    )
    result = await client().post("/rest/api/Suppliers", json={"company_name": "PharmaVet"})
    assert result["data"]["company_name"] == "PharmaVet"


@pytest.mark.asyncio
@respx.mock
async def test_create_supplier_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/Suppliers").mock(
        return_value=httpx.Response(201, json={"data": {"id": 30, "company_name": "PharmaVet"}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("create_supplier", {"company_name": "PharmaVet"})
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_create_timesheet():
    billing_mock()
    respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 100, "doctor_id": 1}})
    )
    result = await client().post("/rest/api/timesheet", json={
        "doctor_id": 1, "begin_datetime": "2026-03-27T09:00:00",
        "end_datetime": "2026-03-27T18:00:00", "clinic_id": 1,
    })
    assert result["data"]["doctor_id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_create_timesheet_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 100, "doctor_id": 1}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("create_timesheet", {
            "doctor_id": 1, "begin_datetime": "2026-03-27T09:00:00",
            "end_datetime": "2026-03-27T18:00:00", "clinic_id": 1,
        })
    assert route.called


# -- Extended update tools (verify expanded fields) --

@pytest.mark.asyncio
@respx.mock
async def test_update_client_extended_fields():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_client", {
            "client_id": 42, "middle_name": "Петрович", "cell_phone": "+79001234567",
            "note": "VIP клиент", "status": "ACTIVE",
        })
    assert route.called
    body = route.calls.last.request.content
    assert b'"middle_name"' in body
    assert b'"cell_phone"' in body
    assert b'"note"' in body
    assert b'"status"' in body


@pytest.mark.asyncio
@respx.mock
async def test_update_pet_extended_fields():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/pet/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("update_pet", {
            "pet_id": 5, "sex": "male", "chip_number": "123456789",
            "weight": "5.2", "color_id": 3,
        })
    assert route.called
    body = route.calls.last.request.content
    assert b'"sex"' in body
    assert b'"chip_number"' in body
    assert b'"weight"' in body
    assert b'"color_id"' in body


@pytest.mark.asyncio
@respx.mock
async def test_update_admission_extended_fields():
    # Stage 96.1: update_admission now maps external pet_id/doctor_id/date
    # to canonical VM API names (patient_id/user_id/admission_date). Only
    # client_id and clinic_id keep their literal keys; pet_id is translated.
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/admission/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        # Stage 108.1: `type` renamed to `admission_type` (builtin shadow fix);
        # payload field name stays `type` at the VM API boundary.
        await mcp.call_tool("update_admission", {
            "admission_id": 1, "client_id": 10, "pet_id": 5,
            "clinic_id": 2, "admission_type": "first_visit",
        })
    assert route.called
    body = route.calls.last.request.content
    assert b'"client_id"' in body
    assert b'"patient_id"' in body  # was "pet_id" before stage 96.1
    assert b'"pet_id"' not in body
    assert b'"clinic_id"' in body
    assert b'"type"' in body


# ── 68.1 Missing tool coverage ──────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice/99").mock(
        return_value=httpx.Response(200, json={"data": {"id": 99, "client_id": 1}})
    )
    result = await client().get("/rest/api/invoice/99")
    assert result["data"]["id"] == 99


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_card_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42, "patient_id": 5}})
    )
    result = await client().get("/rest/api/MedicalCards/42")
    assert result["data"]["id"] == 42


@pytest.mark.asyncio
@respx.mock
async def test_update_medical_card():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42}})
    )
    result = await client().put("/rest/api/MedicalCards/42", json={"description": "Updated"})
    assert route.called
    assert result["data"]["id"] == 42


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_normalizes_response_key():
    """get_medical_cards tool normalizes both 'medicalCards' and 'medicalcards' keys."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": 1, "medicalCards": [{"id": 1}]}
        })
    )
    result = await client().get(
        "/rest/api/MedicalCards",
        params={"filter": '[{"property":"patient_id","value":"5","operator":"="}]', "limit": 20, "offset": 0},
    )
    data = result["data"]
    assert "medicalCards" in data
    assert data["medicalCards"][0]["id"] == 1


# ── 68.2 Error scenario tests ───────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_400_raises_vetmanager_error():
    from exceptions import VetmanagerError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(400, text="Bad request"))
    with pytest.raises(VetmanagerError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_401_raises_auth_error():
    from exceptions import AuthError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(401))
    with pytest.raises(AuthError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_404_raises_not_found_error():
    from exceptions import NotFoundError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/999").mock(return_value=httpx.Response(404))
    with pytest.raises(NotFoundError):
        await client().get("/rest/api/client/999")


@pytest.mark.asyncio
@respx.mock
async def test_422_raises_vetmanager_error():
    from exceptions import VetmanagerError
    billing_mock()
    respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(422, text="Unprocessable")
    )
    with pytest.raises(VetmanagerError):
        await client().post("/rest/api/client", json={"bad": "data"})


@pytest.mark.asyncio
@respx.mock
async def test_429_raises_vetmanager_error():
    from exceptions import VetmanagerError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(429, text="Too many"))
    with pytest.raises(VetmanagerError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_timeout_raises_vetmanager_timeout_error():
    from exceptions import VetmanagerTimeoutError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(VetmanagerTimeoutError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_malformed_json_raises_error():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, text="not json at all")
    )
    with pytest.raises(Exception):
        await client().get("/rest/api/client")
