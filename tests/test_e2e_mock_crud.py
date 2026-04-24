"""E2E mock tests: CRUD operations and error scenarios."""

"""E2E mock/contract tests for all MCP tools via respx."""

import json

import pytest
import respx
import httpx
from fastmcp.exceptions import ToolError

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


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/invoice/10"
    assert _body_of(route) == {"description": "Updated"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/user/5"
    assert _body_of(route) == {"last_name": "Ivanov"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/hospital/3"
    assert _body_of(route) == {"status": "discharged"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/Suppliers/7"
    assert _body_of(route) == {"company_name": "NewCo"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/good/15"
    assert _body_of(route) == {"title": "Updated Good"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "DELETE"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/client/42"


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "DELETE"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/pet/5"


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "DELETE"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/invoice/10"


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "DELETE"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/invoiceDocument/20"


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "POST"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/good"
    assert _body_of(route) == {
        "title": "Vaccine X",
        "is_active": 1,
        "is_for_sale": 1,
    }


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "POST"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/Suppliers"
    assert _body_of(route) == {"company_name": "PharmaVet"}


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "POST"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/timesheet"
    assert _body_of(route) == {
        "doctor_id": 1,
        "begin_datetime": "2026-03-27 09:00:00",
        "end_datetime": "2026-03-27 18:00:00",
        "clinic_id": 1,
    }


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/client/42"
    assert _body_of(route) == {
        "middle_name": "Петрович",
        "cell_phone": "+79001234567",
        "note": "VIP клиент",
        "status": "ACTIVE",
    }


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/pet/5"
    assert _body_of(route) == {
        "sex": "male",
        "chip_number": "123456789",
        "weight": "5.2",
        "color_id": 3,
    }


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/admission/1"
    assert _body_of(route) == {
        "client_id": 10,
        "patient_id": 5,
        "clinic_id": 2,
        "type": "first_visit",
    }


@pytest.mark.asyncio
@respx.mock
async def test_create_good_tool_422_raises_vetmanager_error():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(422, text="Unprocessable")
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="HTTP 422"):
            await mcp.call_tool("create_good", {"title": "Broken"})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_update_user_tool_500_raises_vetmanager_error():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/user/5").mock(
        return_value=httpx.Response(500, text="Server error")
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="HTTP 500"):
            await mcp.call_tool("update_user", {"user_id": 5, "last_name": "Broken"})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_delete_client_tool_404_raises_not_found_error():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(404)
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="Resource not found"):
            await mcp.call_tool("delete_client", {"client_id": 42})

    assert route.call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "route_method", "path", "payload", "status_code", "match"),
    [
        ("create_good", respx.post, "/rest/api/good", {"title": "Broken"}, 422, "HTTP 422"),
        ("create_supplier", respx.post, "/rest/api/Suppliers", {"company_name": "Broken"}, 422, "HTTP 422"),
        (
            "create_timesheet",
            respx.post,
            "/rest/api/timesheet",
            {
                "doctor_id": 1,
                "begin_datetime": "2026-03-27T09:00:00",
                "end_datetime": "2026-03-27T18:00:00",
                "clinic_id": 1,
            },
            422,
            "HTTP 422",
        ),
        ("update_invoice", respx.put, "/rest/api/invoice/10", {"invoice_id": 10, "description": "Broken"}, 500, "HTTP 500"),
        ("update_user", respx.put, "/rest/api/user/5", {"user_id": 5, "last_name": "Broken"}, 500, "HTTP 500"),
        (
            "update_hospitalization",
            respx.put,
            "/rest/api/hospital/3",
            {"hospital_id": 3, "status": "broken"},
            500,
            "HTTP 500",
        ),
        (
            "update_supplier",
            respx.put,
            "/rest/api/Suppliers/7",
            {"supplier_id": 7, "company_name": "Broken"},
            500,
            "HTTP 500",
        ),
        ("update_good", respx.put, "/rest/api/good/15", {"good_id": 15, "title": "Broken"}, 500, "HTTP 500"),
        ("delete_client", respx.delete, "/rest/api/client/42", {"client_id": 42}, 404, "Resource not found"),
        ("delete_pet", respx.delete, "/rest/api/pet/5", {"pet_id": 5}, 404, "Resource not found"),
        ("delete_invoice", respx.delete, "/rest/api/invoice/10", {"invoice_id": 10}, 404, "Resource not found"),
        ("delete_invoice_document", respx.delete, "/rest/api/invoiceDocument/20", {"doc_id": 20}, 404, "Resource not found"),
    ],
)
@respx.mock
async def test_mutation_tools_error_paths_raise_toolerror(
    tool_name,
    route_method,
    path,
    payload,
    status_code,
    match,
):
    billing_mock()
    route = route_method(f"{BASE}{path}").mock(return_value=httpx.Response(status_code, text="boom"))
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match=match):
            await mcp.call_tool(tool_name, payload)

    assert route.call_count == 1


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
    assert route.call_count == 1
    assert route.calls.last.request.method == "PUT"
    assert str(route.calls.last.request.url) == f"{BASE}/rest/api/MedicalCards/42"
    assert _body_of(route) == {"description": "Updated"}
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
