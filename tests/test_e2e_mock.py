"""E2E mock/contract tests for all MCP tools via respx."""

import pytest
import respx
import httpx
from unittest.mock import patch

import request_credentials
from vetmanager_client import VetmanagerClient

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


# ── MedicalCard tools ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards():
    billing_mock()
    respx.get(f"{BASE}/rest/api/medicalcard").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 3, "pet_id": 5}]})
    )
    result = await client().get("/rest/api/medicalcard", params={"pet_id": 5, "limit": 20, "offset": 0})
    assert result["data"][0]["pet_id"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card():
    billing_mock()
    respx.post(f"{BASE}/rest/api/medicalcard").mock(
        return_value=httpx.Response(201, json={"data": {"id": 30, "description": "Checkup"}})
    )
    result = await client().post(
        "/rest/api/medicalcard",
        json={"pet_id": 5, "doctor_id": 3, "date": "2026-03-01", "description": "Checkup"},
    )
    assert result["data"]["description"] == "Checkup"


# ── Invoice tools ─────────────────────────────────────────────────────────────

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
