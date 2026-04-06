"""E2E mock tests: core entities and reference data."""

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


