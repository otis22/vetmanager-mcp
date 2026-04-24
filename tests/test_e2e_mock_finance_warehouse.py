"""E2E mock tests: finance, warehouse, and stock balance."""

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

