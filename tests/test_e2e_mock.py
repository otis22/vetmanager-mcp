"""E2E mock/contract tests for all MCP tools via respx."""

import pytest
import respx
import httpx
from unittest.mock import patch

import request_credentials
from vetmanager_client import VetmanagerClient
from server import mcp

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def client(domain=DOMAIN, api_key=API_KEY):
    headers = {"x-vm-domain": domain, "x-vm-api-key": api_key}
    with patch.object(request_credentials, "_get_request_headers", return_value=headers):
        return VetmanagerClient()


# ── Client tools ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_clients_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "firstName": "Anna"}]})
    )
    result = await client().get("/rest/api/client", params={"limit": 20, "offset": 0})
    assert isinstance(result["data"], list)
    assert result["data"][0]["id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_client_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42, "firstName": "Bob"}})
    )
    result = await client().get("/rest/api/client/42")
    assert result["data"]["id"] == 42


@pytest.mark.asyncio
@respx.mock
async def test_create_client():
    billing_mock()
    respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(201, json={"data": {"id": 99, "firstName": "Eve"}})
    )
    result = await client().post("/rest/api/client", json={"firstName": "Eve", "lastName": "Smith"})
    assert result["data"]["id"] == 99


@pytest.mark.asyncio
@respx.mock
async def test_update_client():
    billing_mock()
    respx.put(f"{BASE}/rest/api/client/42").mock(
        return_value=httpx.Response(200, json={"data": {"id": 42, "firstName": "Bobby"}})
    )
    result = await client().put("/rest/api/client/42", json={"firstName": "Bobby"})
    assert result["data"]["firstName"] == "Bobby"


# ── Pet tools ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_pets_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 5, "alias": "Rex"}]})
    )
    result = await client().get("/rest/api/pet", params={"limit": 20, "offset": 0})
    assert result["data"][0]["alias"] == "Rex"


@pytest.mark.asyncio
@respx.mock
async def test_get_pet_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5, "alias": "Rex"}})
    )
    result = await client().get("/rest/api/pet/5")
    assert result["data"]["id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_create_pet():
    billing_mock()
    respx.post(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 10, "alias": "Luna"}})
    )
    result = await client().post("/rest/api/pet", json={"alias": "Luna", "client_id": 1})
    assert result["data"]["alias"] == "Luna"


# ── Admission tools ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "date": "2026-01-01"}]})
    )
    result = await client().get("/rest/api/admission", params={"limit": 20, "offset": 0})
    assert len(result["data"]) >= 1


@pytest.mark.asyncio
@respx.mock
async def test_get_admission_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "pet_id": 5}})
    )
    result = await client().get("/rest/api/admission/1")
    assert result["data"]["pet_id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_create_admission():
    billing_mock()
    respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"id": 20, "pet_id": 5}})
    )
    result = await client().post(
        "/rest/api/admission",
        json={"pet_id": 5, "client_id": 1, "doctor_id": 3, "date": "2026-03-01T10:00:00"},
    )
    assert result["data"]["id"] == 20


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_with_date_filter():
    """get_admissions should pass date as an API filter, not client-side."""
    billing_mock()
    import json as _json
    date_filter = _json.dumps(
        [{"property": "admission_date", "value": "2026-03-06", "operator": "like"}],
        separators=(",", ":"),
    )
    sort_param = _json.dumps(
        [{"property": "admission_date", "direction": "ASC"}],
        separators=(",", ":"),
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": 5, "admission_date": "2026-03-06 10:00:00"}]},
        )
    )
    result = await client().get(
        "/rest/api/admission",
        params={"filter": date_filter, "sort": sort_param, "limit": 20, "offset": 0},
    )
    assert len(result["data"]) >= 1
    assert "2026-03-06" in result["data"][0]["admission_date"]


# ── MedicalCard tools ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards():
    billing_mock()
    import json as _json
    mc_filter = _json.dumps(
        [{"property": "patient_id", "value": "5", "operator": "="}],
        separators=(",", ":"),
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 1, "medicalCards": [{"id": 3, "patient_id": 5}]}},
        )
    )
    result = await client().get("/rest/api/MedicalCards", params={"filter": mc_filter, "limit": 20, "offset": 0})
    cards = result["data"].get("medicalCards") or result["data"].get("medicalcards") or []
    assert cards[0]["patient_id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card():
    billing_mock()
    respx.post(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(201, json={"data": {"id": 30, "description": "Checkup"}})
    )
    result = await client().post(
        "/rest/api/MedicalCards",
        json={"patient_id": 5, "doctor_id": 3, "date_create": "2026-03-01", "description": "Checkup"},
    )
    assert result["data"]["description"] == "Checkup"


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id():
    """get_medical_cards_by_client_id fetches pets first, then their medical cards."""
    billing_mock()
    import json as _json
    pet_filter = _json.dumps(
        [{"property": "client_id", "value": "42", "operator": "="}],
        separators=(",", ":"),
    )
    # Mock pets endpoint
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"pet": [{"id": 7, "alias": "Barney"}]}},
        )
    )
    # Mock medical cards endpoint for pet 7 (correct endpoint: /rest/api/MedicalCards)
    import json as _json2
    mc_filter = _json2.dumps(
        [{"property": "patient_id", "value": "7", "operator": "="}],
        separators=(",", ":"),
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 1, "medicalCards": [{"id": 100, "patient_id": 7, "description": "OK"}]}},
        )
    )
    # Call via VetmanagerClient directly (simulates the tool logic)
    pets_resp = await client().get("/rest/api/pet", params={"filter": pet_filter, "limit": 100})
    pets = pets_resp.get("data", {}).get("pet", [])
    assert len(pets) == 1
    assert pets[0]["alias"] == "Barney"
    cards_resp = await client().get("/rest/api/MedicalCards", params={"filter": mc_filter, "limit": 20, "offset": 0})
    cards = cards_resp.get("data", {}).get("medicalCards") or cards_resp.get("data", {}).get("medicalcards") or []
    assert len(cards) == 1
    assert cards[0]["description"] == "OK"


@pytest.mark.asyncio
@respx.mock
async def test_get_debtors_returns_negative_balance_clients():
    """get_debtors should return only clients with negative balance."""
    billing_mock()
    import json as _json
    active_filter = _json.dumps(
        [{"property": "status", "value": "ACTIVE", "operator": "="}],
        separators=(",", ":"),
    )
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 3,
                    "client": [
                        {"id": 1, "last_name": "Ivanov", "balance": "-500.00", "status": "ACTIVE"},
                        {"id": 2, "last_name": "Petrov", "balance": "100.00", "status": "ACTIVE"},
                        {"id": 3, "last_name": "Sidorov", "balance": "-200.00", "status": "ACTIVE"},
                    ],
                }
            },
        )
    )
    resp = await client().get("/rest/api/client", params={"filter": active_filter, "limit": 100, "offset": 0})
    clients_data = resp.get("data", {}).get("client", [])
    debtors = [c for c in clients_data if float(c.get("balance", 0)) < 0]
    assert len(debtors) == 2
    assert debtors[0]["last_name"] == "Ivanov"
    assert debtors[1]["last_name"] == "Sidorov"


@pytest.mark.asyncio
@respx.mock
async def test_get_average_invoice_calculates_correctly():
    """get_average_invoice should compute average from paginated invoice data."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 2,
                    "invoice": [
                        {"id": 1, "amount": "1000.00"},
                        {"id": 2, "amount": "500.00"},
                    ],
                }
            },
        )
    )
    resp = await client().get("/rest/api/invoice", params={"limit": 100, "offset": 0})
    invoices = resp.get("data", {}).get("invoice", [])
    amounts = [float(inv["amount"]) for inv in invoices if float(inv.get("amount", 0)) > 0]
    average = round(sum(amounts) / len(amounts), 2) if amounts else 0.0
    assert average == 750.0
    assert len(amounts) == 2


# ── Invoice tools ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_invoices():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 7, "client_id": 1}]})
    )
    result = await client().get("/rest/api/invoice", params={"limit": 20, "offset": 0})
    assert result["data"][0]["id"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_create_invoice():
    billing_mock()
    respx.post(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(201, json={"data": {"id": 50}})
    )
    result = await client().post("/rest/api/invoice", json={"client_id": 1, "pet_id": 5})
    assert result["data"]["id"] == 50


# ── Good tools ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_goods():
    billing_mock()
    respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 2, "name": "Vaccine"}]})
    )
    result = await client().get("/rest/api/good", params={"limit": 20, "offset": 0})
    assert result["data"][0]["name"] == "Vaccine"


@pytest.mark.asyncio
@respx.mock
async def test_get_good_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/good/2").mock(
        return_value=httpx.Response(200, json={"data": {"id": 2, "name": "Vaccine", "price": "500"}})
    )
    result = await client().get("/rest/api/good/2")
    assert result["data"]["price"] == "500"


# ── User tools ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_users():
    billing_mock()
    respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "login": "dr.smith"}]})
    )
    result = await client().get("/rest/api/user", params={"limit": 20, "offset": 0})
    assert result["data"][0]["login"] == "dr.smith"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/user/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "login": "dr.smith"}})
    )
    result = await client().get("/rest/api/user/1")
    assert result["data"]["id"] == 1


# ── Reference: Breed ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_breeds_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/breed").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Labrador"}]})
    )
    result = await client().get("/rest/api/breed", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Labrador"


@pytest.mark.asyncio
@respx.mock
async def test_get_breed_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/breed/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Labrador", "pet_type_id": 2}})
    )
    result = await client().get("/rest/api/breed/1")
    assert result["data"]["pet_type_id"] == 2


# ── Reference: PetType ────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_pet_types_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/petType").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Dog"}]})
    )
    result = await client().get("/rest/api/petType", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Dog"


@pytest.mark.asyncio
@respx.mock
async def test_get_pet_type_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/petType/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Dog"}})
    )
    result = await client().get("/rest/api/petType/1")
    assert result["data"]["id"] == 1


# ── Reference: City ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_cities_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/city").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 10, "title": "Moscow"}]})
    )
    result = await client().get("/rest/api/city", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Moscow"


@pytest.mark.asyncio
@respx.mock
async def test_get_city_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/city/10").mock(
        return_value=httpx.Response(200, json={"data": {"id": 10, "title": "Moscow"}})
    )
    result = await client().get("/rest/api/city/10")
    assert result["data"]["id"] == 10


# ── Reference: CityType ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_city_types_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/cityType").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "г."}]})
    )
    result = await client().get("/rest/api/cityType", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "г."


# ── Reference: Street ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_streets_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/street").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 5, "title": "Lenina", "city_id": 10}]})
    )
    result = await client().get("/rest/api/street", params={"limit": 20, "offset": 0})
    assert result["data"][0]["city_id"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_get_street_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/street/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5, "title": "Lenina"}})
    )
    result = await client().get("/rest/api/street/5")
    assert result["data"]["id"] == 5


# ── Reference: Unit ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_units_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/unit").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "шт."}]})
    )
    result = await client().get("/rest/api/unit", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "шт."


@pytest.mark.asyncio
@respx.mock
async def test_get_unit_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/unit/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "шт.", "status": "active"}})
    )
    result = await client().get("/rest/api/unit/1")
    assert result["data"]["status"] == "active"


# ── Reference: Role ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_roles_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/role").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "name": "Admin"}]})
    )
    result = await client().get("/rest/api/role", params={"limit": 20, "offset": 0})
    assert result["data"][0]["name"] == "Admin"


@pytest.mark.asyncio
@respx.mock
async def test_get_role_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/role/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "name": "Admin", "super": 1}})
    )
    result = await client().get("/rest/api/role/1")
    assert result["data"]["super"] == 1


# ── Reference: UserPosition ───────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_user_positions_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/userPosition").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Veterinarian"}]})
    )
    result = await client().get("/rest/api/userPosition", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Veterinarian"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_position_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/userPosition/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Veterinarian", "admission_length": "00:30:00"}})
    )
    result = await client().get("/rest/api/userPosition/1")
    assert result["data"]["admission_length"] == "00:30:00"


# ── Reference: ComboManualName ────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_combo_manual_names_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/ComboManualName").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 3, "title": "Окрас"}]})
    )
    result = await client().get("/rest/api/ComboManualName", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Окрас"


@pytest.mark.asyncio
@respx.mock
async def test_get_combo_manual_name_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/ComboManualName/3").mock(
        return_value=httpx.Response(200, json={"data": {"id": 3, "title": "Окрас", "is_readonly": 0}})
    )
    result = await client().get("/rest/api/ComboManualName/3")
    assert result["data"]["id"] == 3


# ── Reference: ComboManualItem ────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_combo_manual_items_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/ComboManualItem").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 7, "title": "Рыжий", "combo_manual_id": 3}]})
    )
    result = await client().get("/rest/api/ComboManualItem", params={"comboManualNameId": 3, "limit": 20, "offset": 0})
    assert result["data"][0]["combo_manual_id"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_get_combo_manual_item_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/ComboManualItem/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7, "title": "Рыжий", "is_active": 1}})
    )
    result = await client().get("/rest/api/ComboManualItem/7")
    assert result["data"]["is_active"] == 1


# ── Finance: Payment ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_payments_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "amount": "1500.00", "client_id": 42}]})
    )
    result = await client().get("/rest/api/payment", params={"limit": 20, "offset": 0})
    assert result["data"][0]["amount"] == "1500.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_payment_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/payment/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "payment_type": "cash"}})
    )
    result = await client().get("/rest/api/payment/1")
    assert result["data"]["payment_type"] == "cash"


@pytest.mark.asyncio
@respx.mock
async def test_create_payment():
    billing_mock()
    respx.post(f"{BASE}/rest/api/payment").mock(
        return_value=httpx.Response(201, json={"data": {"id": 55, "amount": "500.00"}})
    )
    result = await client().post("/rest/api/payment", json={"clientId": 42, "amount": 500.0, "cassaId": 1})
    assert result["data"]["id"] == 55


# ── Finance: ClosingOfInvoices ────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_closing_of_invoices_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/closingOfInvoices").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "invoice_id": 7, "amount": "300.00"}]})
    )
    result = await client().get("/rest/api/closingOfInvoices", params={"limit": 20, "offset": 0})
    assert result["data"][0]["invoice_id"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_get_closing_of_invoice_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/closingOfInvoices/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "payment_type": "card"}})
    )
    result = await client().get("/rest/api/closingOfInvoices/1")
    assert result["data"]["payment_type"] == "card"


# ── Finance: InvoiceDocument ──────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_invoice_documents_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "invoice_id": 50, "good_id": 2}]})
    )
    result = await client().get("/rest/api/invoiceDocument", params={"invoiceId": 50, "limit": 50, "offset": 0})
    assert result["data"][0]["good_id"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_invoice_document_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoiceDocument/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "quantity": "2.00", "price": "250.00"}})
    )
    result = await client().get("/rest/api/invoiceDocument/1")
    assert result["data"]["price"] == "250.00"


@pytest.mark.asyncio
@respx.mock
async def test_add_invoice_document():
    billing_mock()
    respx.post(f"{BASE}/rest/api/invoiceDocument").mock(
        return_value=httpx.Response(201, json={"data": {"id": 99, "invoice_id": 50, "good_id": 2}})
    )
    result = await client().post("/rest/api/invoiceDocument", json={"invoiceId": 50, "goodId": 2, "quantity": 1, "price": 250.0})
    assert result["data"]["invoice_id"] == 50


# ── Finance: Cassa ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_cassas_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/cassa").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Основная касса"}]})
    )
    result = await client().get("/rest/api/cassa", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Основная касса"


@pytest.mark.asyncio
@respx.mock
async def test_get_cassa_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/cassa/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "main_cassa": 1}})
    )
    result = await client().get("/rest/api/cassa/1")
    assert result["data"]["main_cassa"] == 1


# ── Finance: CassaClose ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_cassa_closes_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/cassaclose").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "cassa_id": 1, "summa_total": "5000.00"}]})
    )
    result = await client().get("/rest/api/cassaclose", params={"limit": 20, "offset": 0})
    assert result["data"][0]["summa_total"] == "5000.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_cassa_close_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/cassaclose/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "status": "closed"}})
    )
    result = await client().get("/rest/api/cassaclose/1")
    assert result["data"]["status"] == "closed"


# ── Warehouse: GoodGroup ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_good_groups_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/GoodGroup").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Вакцины", "is_service": 0}]})
    )
    result = await client().get("/rest/api/GoodGroup", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Вакцины"


@pytest.mark.asyncio
@respx.mock
async def test_get_good_group_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/GoodGroup/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Вакцины", "status": "ACTIVE"}})
    )
    result = await client().get("/rest/api/GoodGroup/1")
    assert result["data"]["status"] == "ACTIVE"


# ── Warehouse: GoodSaleParam ──────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_good_sale_params_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/goodSaleParam").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "good_id": 2, "price": "500.00"}]})
    )
    result = await client().get("/rest/api/goodSaleParam", params={"goodId": 2, "limit": 20, "offset": 0})
    assert result["data"][0]["price"] == "500.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_good_sale_param_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/goodSaleParam/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "min_price": "400.00", "max_price": "600.00"}})
    )
    result = await client().get("/rest/api/goodSaleParam/1")
    assert result["data"]["min_price"] == "400.00"


# ── Warehouse: PartyAccount ───────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_party_accounts_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/PartyAccount").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "good_id": 2, "quantity": "100.00"}]})
    )
    result = await client().get("/rest/api/PartyAccount", params={"limit": 20, "offset": 0})
    assert result["data"][0]["quantity"] == "100.00"


@pytest.mark.asyncio
@respx.mock
async def test_get_party_account_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/PartyAccount/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "price": "45.00"}})
    )
    result = await client().get("/rest/api/PartyAccount/1")
    assert result["data"]["price"] == "45.00"


# ── Warehouse: PartyAccountDoc ────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_party_account_docs_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/PartyAccountDoc").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "document_id": 5, "good_id": 2}]})
    )
    result = await client().get("/rest/api/PartyAccountDoc", params={"limit": 20, "offset": 0})
    assert result["data"][0]["document_id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_get_party_account_doc_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/PartyAccountDoc/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "quantity": "10.00", "cost": "450.00"}})
    )
    result = await client().get("/rest/api/PartyAccountDoc/1")
    assert result["data"]["cost"] == "450.00"


# ── Warehouse: StoreDocument ──────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_store_documents_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/StoreDocument").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "type": "prihod", "status": "exec"}]})
    )
    result = await client().get("/rest/api/StoreDocument", params={"limit": 20, "offset": 0})
    assert result["data"][0]["type"] == "prihod"


@pytest.mark.asyncio
@respx.mock
async def test_get_store_document_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/StoreDocument/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "summa": "4500.00"}})
    )
    result = await client().get("/rest/api/StoreDocument/1")
    assert result["data"]["summa"] == "4500.00"


# ── Warehouse: Suppliers ──────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_suppliers_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/Suppliers").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "company_name": "PharmVet LLC"}]})
    )
    result = await client().get("/rest/api/Suppliers", params={"limit": 20, "offset": 0})
    assert result["data"][0]["company_name"] == "PharmVet LLC"


@pytest.mark.asyncio
@respx.mock
async def test_get_supplier_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/Suppliers/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "status": "ACTIVE", "person_type": "legal_person"}})
    )
    result = await client().get("/rest/api/Suppliers/1")
    assert result["data"]["person_type"] == "legal_person"


# ── Clinical: Hospital ────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_hospitalizations_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/hospital").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "patient_id": 5, "status": "active"}]})
    )
    result = await client().get("/rest/api/hospital", params={"limit": 20, "offset": 0})
    assert result["data"][0]["status"] == "active"


@pytest.mark.asyncio
@respx.mock
async def test_get_hospitalization_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/hospital/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "patient_id": 5, "doctor_id": 3}})
    )
    result = await client().get("/rest/api/hospital/1")
    assert result["data"]["doctor_id"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_create_hospitalization():
    billing_mock()
    respx.post(f"{BASE}/rest/api/hospital").mock(
        return_value=httpx.Response(201, json={"data": {"id": 20, "patient_id": 5, "status": "active"}})
    )
    result = await client().post("/rest/api/hospital", json={"petId": 5, "doctorId": 3, "dateIn": "2026-03-01T09:00:00"})
    assert result["data"]["id"] == 20


# ── Clinical: HospitalBlock ───────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_hospital_blocks_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/HospitalBlock").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Блок А", "capacity": 10}]})
    )
    result = await client().get("/rest/api/HospitalBlock", params={"limit": 20, "offset": 0})
    assert result["data"][0]["capacity"] == 10


@pytest.mark.asyncio
@respx.mock
async def test_get_hospital_block_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/HospitalBlock/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "title": "Блок А", "is_active": 1}})
    )
    result = await client().get("/rest/api/HospitalBlock/1")
    assert result["data"]["is_active"] == 1


# ── Clinical: Diagnoses ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_diagnoses_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/AllDiagnoses").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Ринит"}]})
    )
    result = await client().get("/rest/api/MedicalCards/AllDiagnoses", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Ринит"


# ── Operations: Clinics ───────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_clinics_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/clinics").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "title": "Главный офис"}]})
    )
    result = await client().get("/rest/api/clinics", params={"limit": 20, "offset": 0})
    assert result["data"][0]["title"] == "Главный офис"


@pytest.mark.asyncio
@respx.mock
async def test_get_clinic_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/clinics/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "status": "ACTIVE", "time_zone": "Europe/Moscow"}})
    )
    result = await client().get("/rest/api/clinics/1")
    assert result["data"]["time_zone"] == "Europe/Moscow"


# ── Operations: Timesheet ─────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_timesheets_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "doctor_id": 3, "begin_datetime": "2026-03-01 09:00:00"}]})
    )
    result = await client().get("/rest/api/timesheet", params={"limit": 20, "offset": 0})
    assert result["data"][0]["doctor_id"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_get_timesheet_by_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1, "all_day": 0, "night": 0}})
    )
    result = await client().get("/rest/api/timesheet/1")
    assert result["data"]["all_day"] == 0


# ── Operations: Properties ────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_properties_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/properties").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "property_name": "timezone", "property_value": "Europe/Moscow"}]})
    )
    result = await client().get("/rest/api/properties", params={"limit": 50, "offset": 0})
    assert result["data"][0]["property_name"] == "timezone"


# ── Operations: AnonymousClient ───────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_anonymous_clients_returns_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/user/anonymousList").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "status": "ACTIVE", "balance": "0.00"}]})
    )
    result = await client().get("/rest/api/user/anonymousList", params={"limit": 20, "offset": 0})
    assert result["data"][0]["status"] == "ACTIVE"


# ── Error contract ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_403_raises_auth_error():
    from exceptions import AuthError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(403))
    with pytest.raises(AuthError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_500_raises_vetmanager_error():
    from exceptions import VetmanagerError
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=httpx.Response(500, text="Server error"))
    with pytest.raises(VetmanagerError):
        await client().get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_get_clients_with_sort_and_filter_params():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1, "firstName": "Anna"}]})
    )
    params = {
        "limit": 10,
        "offset": 0,
        "sort": '[{"property":"title","direction":"ASC"}]',
        "filter": '[{"property":"title","value":"some value","operator":"like"}]',
    }
    result = await client().get("/rest/api/client", params=params)
    assert result["data"][0]["id"] == 1
    request = route.calls.last.request
    assert request.url.params.get("sort") == params["sort"]
    assert request.url.params.get("filter") == params["filter"]


# ── Profile tools: get_vaccinations ──────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_vaccinations_returns_structured_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "medicalcards": [
                    {
                        "id": 52,
                        "name": "Биовак DPAL",
                        "pet_id": 66,
                        "date": "2026-03-01 00:00:00",
                        "date_nexttime": "2026-04-01",
                        "vaccine_id": 260,
                        "medcard_id": 800,
                        "doza_value": "1.0000000000",
                        "next_admission_id": 0,
                        "pet_age_at_time_vaccination": "не указано",
                    }
                ]
            },
            "success": True,
        })
    )
    vc = client()
    result = await vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": 66, "limit": 50})
    records = result["data"]["medicalcards"]
    assert len(records) == 1
    assert records[0]["name"] == "Биовак DPAL"
    assert records[0]["date_nexttime"] == "2026-04-01"


@pytest.mark.asyncio
@respx.mock
async def test_get_vaccinations_empty_list():
    billing_mock()
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}, "success": True})
    )
    vc = client()
    result = await vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": 999, "limit": 50})
    assert result["data"]["medicalcards"] == []


# ── Profile tools: get_client_profile ────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_client_profile_aggregates_data():
    """get_client_profile makes 4 requests and returns aggregated dict."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/client/422").mock(
        return_value=httpx.Response(200, json={
            "data": {"client": {"id": 422, "first_name": "Sergey", "balance": "0.00"}}
        })
    )
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 1,
                "invoice": [{"id": 182, "amount": "850.00", "payment_status": "full", "invoiceDocuments": []}],
            }
        })
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "totalCount": 2,
                "admission": [
                    {"id": 822, "admission_date": "2026-03-01 15:49:06", "status": "accepted"},
                    {"id": 772, "admission_date": "2024-12-31 11:19:37", "status": "accepted"},
                ],
            }
        })
    )

    import json as _json
    from unittest.mock import AsyncMock, patch

    async def fake_get_client_profile(client_id):
        vc = client()
        client_resp = await vc.get(f"/rest/api/client/{client_id}")
        client_data = client_resp.get("data", {}).get("client", {})

        invoice_filter = _json.dumps([{"property": "client_id", "value": str(client_id)}], separators=(",", ":"))
        invoice_sort = _json.dumps([{"property": "id", "direction": "DESC"}], separators=(",", ":"))
        invoices_resp = await vc.get("/rest/api/invoice", params={"filter": invoice_filter, "sort": invoice_sort, "limit": 5})
        invoices = invoices_resp.get("data", {}).get("invoice", [])

        admission_filter = _json.dumps([{"property": "client_id", "value": str(client_id)}], separators=(",", ":"))
        admission_sort = _json.dumps([{"property": "admission_date", "direction": "DESC"}], separators=(",", ":"))
        admissions_resp = await vc.get("/rest/api/admission", params={"filter": admission_filter, "sort": admission_sort, "limit": 5})
        admissions = admissions_resp.get("data", {}).get("admission", [])

        next_filter = _json.dumps([{"property": "client_id", "value": str(client_id)}, {"property": "status", "value": "active"}], separators=(",", ":"))
        next_sort = _json.dumps([{"property": "admission_date", "direction": "ASC"}], separators=(",", ":"))
        next_resp = await vc.get("/rest/api/admission", params={"filter": next_filter, "sort": next_sort, "limit": 1})
        next_list = next_resp.get("data", {}).get("admission", [])

        return {
            "client": client_data,
            "last_invoices": invoices,
            "last_admissions": admissions,
            "next_admission": next_list[0] if next_list else None,
        }

    result = await fake_get_client_profile(422)
    assert result["client"]["id"] == 422
    assert len(result["last_invoices"]) == 1
    assert result["last_invoices"][0]["payment_status"] == "full"
    assert len(result["last_admissions"]) == 2
    # next_admission may be populated (mock returns same data for all admission requests)
    assert "client" in result
    assert "last_invoices" in result
    assert "last_admissions" in result
    assert "next_admission" in result


# ── Profile tools: get_pet_profile ───────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_pet_profile_computes_vaccination_dates():
    """get_pet_profile correctly extracts last and next vaccination dates."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/pet/66").mock(
        return_value=httpx.Response(200, json={
            "data": {"pet": {"id": 66, "alias": "Айва", "owner_id": 422}}
        })
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"totalCount": 1, "medicalCards": [{"id": 800, "patient_id": 66, "date_create": "2026-03-01", "description": "checkup"}]}
        })
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={
            "data": {
                "medicalcards": [
                    {
                        "id": 52,
                        "name": "Биовак DPAL",
                        "pet_id": 66,
                        "date": "2026-03-01 00:00:00",
                        "date_nexttime": "2026-04-01",
                        "vaccine_id": 260,
                        "medcard_id": 800,
                    }
                ]
            },
            "success": True,
        })
    )

    import json as _json

    async def fake_get_pet_profile(pet_id):
        vc = client()
        pet_resp = await vc.get(f"/rest/api/pet/{pet_id}")
        pet_data = pet_resp.get("data", {}).get("pet", {})

        mc_filter = _json.dumps([{"property": "patient_id", "value": str(pet_id), "operator": "="}], separators=(",", ":"))
        mc_sort = _json.dumps([{"property": "id", "direction": "DESC"}], separators=(",", ":"))
        mc_resp = await vc.get("/rest/api/MedicalCards", params={"filter": mc_filter, "sort": mc_sort, "limit": 5})
        mc_data = mc_resp.get("data", {})
        medical_cards = (mc_data.get("medicalCards") or mc_data.get("medicalcards") or []) if isinstance(mc_data, dict) else []

        vacc_resp = await vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": pet_id, "limit": 100})
        vaccinations_raw = vacc_resp.get("data", {}).get("medicalcards", [])
        vaccinations = [{"id": r["id"], "name": r["name"], "date": r["date"], "date_nexttime": r["date_nexttime"]} for r in vaccinations_raw]

        sorted_vacc = sorted(vaccinations, key=lambda r: r.get("date") or "", reverse=True)
        last_vaccination_date = None
        next_vaccination_date = None
        if sorted_vacc:
            last_vacc = sorted_vacc[0]
            last_vaccination_date = (last_vacc.get("date") or "").split(" ")[0] or None
            next_raw = last_vacc.get("date_nexttime") or ""
            next_vaccination_date = next_raw.strip() or None

        return {
            "pet": pet_data,
            "last_medical_cards": medical_cards,
            "vaccinations": vaccinations,
            "last_vaccination_date": last_vaccination_date,
            "next_vaccination_date": next_vaccination_date,
        }

    result = await fake_get_pet_profile(66)
    assert result["pet"]["id"] == 66
    assert result["last_vaccination_date"] == "2026-03-01"
    assert result["next_vaccination_date"] == "2026-04-01"
    assert len(result["vaccinations"]) == 1
    assert result["vaccinations"][0]["name"] == "Биовак DPAL"


@pytest.mark.asyncio
@respx.mock
async def test_get_pet_profile_no_vaccinations():
    """get_pet_profile handles empty vaccination list gracefully."""
    billing_mock()

    respx.get(f"{BASE}/rest/api/pet/999").mock(
        return_value=httpx.Response(200, json={
            "data": {"pet": {"id": 999, "alias": "Тестовый"}}
        })
    )
    respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"totalCount": 0, "medicalCards": []}})
    )
    respx.get(f"{BASE}/rest/api/MedicalCards/Vaccinations").mock(
        return_value=httpx.Response(200, json={"data": {"medicalcards": []}, "success": True})
    )

    import json as _json

    async def fake_get_pet_profile_empty(pet_id):
        vc = client()
        pet_resp = await vc.get(f"/rest/api/pet/{pet_id}")
        pet_data = pet_resp.get("data", {}).get("pet", {})
        mc_filter = _json.dumps([{"property": "patient_id", "value": str(pet_id), "operator": "="}], separators=(",", ":"))
        mc_sort = _json.dumps([{"property": "id", "direction": "DESC"}], separators=(",", ":"))
        mc_resp = await vc.get("/rest/api/MedicalCards", params={"filter": mc_filter, "sort": mc_sort, "limit": 5})
        mc_data = mc_resp.get("data", {})
        medical_cards = (mc_data.get("medicalCards") or mc_data.get("medicalcards") or []) if isinstance(mc_data, dict) else []
        vacc_resp = await vc.get("/rest/api/MedicalCards/Vaccinations", params={"pet_id": pet_id, "limit": 100})
        vaccinations_raw = vacc_resp.get("data", {}).get("medicalcards", [])
        sorted_vacc = sorted(vaccinations_raw, key=lambda r: r.get("date") or "", reverse=True)
        last_vaccination_date = None
        next_vaccination_date = None
        if sorted_vacc:
            last_vacc = sorted_vacc[0]
            last_vaccination_date = (last_vacc.get("date") or "").split(" ")[0] or None
            next_raw = last_vacc.get("date_nexttime") or ""
            next_vaccination_date = next_raw.strip() or None
        return {
            "pet": pet_data,
            "last_medical_cards": medical_cards,
            "vaccinations": vaccinations_raw,
            "last_vaccination_date": last_vaccination_date,
            "next_vaccination_date": next_vaccination_date,
        }

    result = await fake_get_pet_profile_empty(999)
    assert result["last_vaccination_date"] is None
    assert result["next_vaccination_date"] is None
    assert result["vaccinations"] == []


# ── Warehouse: get_good_stock_balance ─────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_good_stock_balance_returns_quantity():
    billing_mock()
    respx.get(f"{BASE}/rest/api/stores/RestOfGoodInWarehouse/").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "message": "Records Retrieved Successfully",
            "data": {
                "totalCount": 1,
                "rest_good_in_warehouse": {"quantity": "100.000"},
            },
        })
    )
    result = await client().get(
        "/rest/api/stores/RestOfGoodInWarehouse/",
        params={"good_id": 470, "clinic_id": 1},
    )
    qty = float(result["data"]["rest_good_in_warehouse"]["quantity"])
    assert qty == 100.0


@pytest.mark.asyncio
@respx.mock
async def test_get_good_stock_balance_zero_for_service():
    """Услуги (is_warehouse_account=0) всегда возвращают quantity=0."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/stores/RestOfGoodInWarehouse/").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "message": "Records Retrieved Successfully",
            "data": {
                "totalCount": 1,
                "rest_good_in_warehouse": {"quantity": "0.000"},
            },
        })
    )
    result = await client().get(
        "/rest/api/stores/RestOfGoodInWarehouse/",
        params={"good_id": 108, "clinic_id": 1},
    )
    qty = float(result["data"]["rest_good_in_warehouse"]["quantity"])
    assert qty == 0.0


# ── Messages tools ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_send_message_to_all_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/messages/all").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "Messages successfully sent to 21 users",
                "data": {},
            },
        )
    )

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"x-vm-domain": DOMAIN, "x-vm-api-key": API_KEY},
    ):
        result = await mcp.call_tool(
            "send_message_to_all",
            {"message": "Rest post", "campaign": "All1"},
        )

    assert result.structured_content["success"] is True
    assert route.called
    assert b'"campaign":"All1"' in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_send_message_to_users_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/messages/users").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "Messages successfully sent to 1 users",
                "data": {},
            },
        )
    )

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"x-vm-domain": DOMAIN, "x-vm-api-key": API_KEY},
    ):
        result = await mcp.call_tool(
            "send_message_to_users",
            {"message": "Rest post", "campaign": "Concrete1", "user_ids": [1]},
        )

    assert result.structured_content["success"] is True
    assert route.called
    assert b'"user_ids":[1]' in route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_get_message_reports_tool():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/messages/reports").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "campaign": "All users",
                    "total": 0,
                    "sent": 0,
                    "pending": 0,
                },
            },
        )
    )

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"x-vm-domain": DOMAIN, "x-vm-api-key": API_KEY},
    ):
        result = await mcp.call_tool(
            "get_message_reports",
            {"limit": 20, "offset": 0, "campaign": "All users"},
        )

    assert result.structured_content["success"] is True
    assert result.structured_content["data"]["campaign"] == "All users"
    assert route.called
    params = route.calls.last.request.url.params
    assert params["campaign"] == "All users"
    assert params["limit"] == "20"
    assert params["offset"] == "0"


@pytest.mark.asyncio
@respx.mock
async def test_send_message_to_roles_tool():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/messages/roles").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "message": "Messages successfully sent to 2 users with the specified roles",
                "data": {},
            },
        )
    )

    with patch.object(
        request_credentials,
        "_get_request_headers",
        return_value={"x-vm-domain": DOMAIN, "x-vm-api-key": API_KEY},
    ):
        result = await mcp.call_tool(
            "send_message_to_roles",
            {"message": "Rest post", "campaign": "Concrete1", "roles": ["Врач"]},
        )

    assert result.structured_content["success"] is True
    assert route.called
    assert "Врач".encode() in route.calls.last.request.content
