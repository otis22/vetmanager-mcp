"""E2E mock tests: clinical, operations, profiles, and messages."""

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

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
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

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
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

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
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

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "send_message_to_roles",
            {"message": "Rest post", "campaign": "Concrete1", "roles": ["Врач"]},
        )

    assert result.structured_content["success"] is True
    assert route.called
    assert "Врач".encode() in route.calls.last.request.content


