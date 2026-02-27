"""E2E mock/contract tests for all MCP tools via respx."""

import pytest
import respx
import httpx

from vetmanager_client import VetmanagerClient

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def client(domain=DOMAIN, api_key=API_KEY):
    return VetmanagerClient(domain, api_key)


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
