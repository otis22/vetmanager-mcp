"""Stage 321 — MCP field names follow the observed Vetmanager contract."""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from exceptions import ToolInputError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


def admission_read(admission_id: int = 42):
    return respx.get(f"{BASE}/rest/api/admission/{admission_id}").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 1,
                    "admission": {
                        "id": admission_id,
                        "clinic_id": 9,
                        "admission_date": "2034-03-21 10:11:00",
                        "admission_length": "00:30:00",
                    },
                }
            },
        )
    )


@pytest.mark.asyncio
@respx.mock
async def test_create_admission_maps_reason_and_required_clinic_to_real_fields():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(201, json={"data": {"admission": {"id": 42}}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_admission",
            {
                "pet_id": 5,
                "client_id": 1,
                "doctor_id": 3,
                "clinic_id": 9,
                "date": "2034-03-21T10:11:00",
                "reason": "stage321 create",
            },
        )

    assert body_of(route) == {
        "patient_id": 5,
        "client_id": 1,
        "user_id": 3,
        "clinic_id": 9,
        "admission_date": "2034-03-21 10:11:00",
        "description": "stage321 create",
    }


@pytest.mark.asyncio
@respx.mock
async def test_update_admission_maps_reason_and_numeric_type_with_context():
    billing_mock()
    admission_read()
    route = respx.put(f"{BASE}/rest/api/admission/42").mock(
        return_value=httpx.Response(201, json={"data": {"admission": 42}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_admission",
            {
                "admission_id": 42,
                "reason": "stage321 update",
                "admission_type": 7,
            },
        )

    assert body_of(route) == {
        "clinic_id": 9,
        "start": "2034-03-21 10:11:00",
        "end": "2034-03-21 10:41:00",
        "description": "stage321 update",
        "type_id": 7,
    }


@pytest.mark.asyncio
@respx.mock
async def test_hospital_pet_filter_uses_model_field_accepted_by_allowlist():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/hospital").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"totalCount": 1, "hospital": [{"id": 2, "pet_id": 6}]}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_hospitalizations", {"pet_id": 6})

    query = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    filters = json.loads(query["filter"][0])
    assert filters == [{"property": "pet_id", "value": 6, "operator": "="}]


def timesheet_response(rows: list[dict]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"success": True, "data": {"totalCount": len(rows), "timesheet": rows}},
    )


def empty_admissions() -> httpx.Response:
    return httpx.Response(
        200,
        json={"success": True, "data": {"totalCount": 0, "admission": []}},
    )


@pytest.mark.asyncio
@respx.mock
async def test_free_slots_use_only_attached_working_timesheet_types():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=timesheet_response(
            [
                {
                    "id": 1,
                    "doctor_id": 1,
                    "begin_datetime": "2034-03-21 09:00:00",
                    "end_datetime": "2034-03-21 10:00:00",
                    "clinic_id": 1,
                    "type": 2,
                    "ttype": {"id": 2, "is_working_hours": 1},
                },
                {
                    "id": 2,
                    "doctor_id": 1,
                    "begin_datetime": "2034-03-21 10:00:00",
                    "end_datetime": "2034-03-21 11:00:00",
                    "clinic_id": 1,
                    "type": 3,
                    "ttype": {"id": 3, "is_working_hours": 0},
                },
            ]
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(return_value=empty_admissions())
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2034-03-21",
                "date_to": "2034-03-21",
                "slot_minutes": 30,
            },
        )

    data = result.structured_content
    assert [slot["start"] for slot in data["slots"]] == [
        "2034-03-21T09:00:00",
        "2034-03-21T09:30:00",
    ]
    query = parse_qs(urlparse(str(route.calls.last.request.url)).query)
    assert json.loads(query["parameters"][0]) == {"attach_timesheet_type": 1}


@pytest.mark.asyncio
@respx.mock
async def test_free_slots_keep_stage311_all_day_and_night_geometry():
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=timesheet_response(
            [
                {
                    "id": 1,
                    "begin_datetime": "2034-03-21 00:00:00",
                    "end_datetime": "2034-03-21 23:59:59",
                    "clinic_id": 1,
                    "type": 2,
                    "all_day": 1,
                    "night": 0,
                    "ttype": {"id": 2, "is_working_hours": 1},
                },
                {
                    "id": 2,
                    "begin_datetime": "2034-03-21 22:00:00",
                    "end_datetime": "2034-03-22 02:00:00",
                    "clinic_id": 2,
                    "type": 2,
                    "all_day": 0,
                    "night": 1,
                    "ttype": {"id": 2, "is_working_hours": 1},
                },
            ]
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(return_value=empty_admissions())
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2034-03-21",
                "date_to": "2034-03-21",
                "slot_minutes": 120,
                "min_slot_minutes": 15,
            },
        )

    slots = result.structured_content["slots"]
    assert any(slot["clinic_id"] == 1 and slot["start"] == "2034-03-21T00:00:00" for slot in slots)
    assert any(slot["clinic_id"] == 2 and slot["end"] == "2034-03-22T00:00:00" for slot in slots)


@pytest.mark.asyncio
@respx.mock
async def test_nonempty_timesheet_without_attached_type_is_contract_error():
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=timesheet_response(
            [
                {
                    "id": 1,
                    "begin_datetime": "2034-03-21 09:00:00",
                    "end_datetime": "2034-03-21 10:00:00",
                    "clinic_id": 1,
                    "type": 2,
                }
            ]
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(return_value=empty_admissions())
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(
        Exception, match="timesheet type|working-hours discriminator"
    ):
        await mcp.call_tool(
            "get_doctor_free_slots",
            {"doctor_id": 1, "date_from": "2034-03-21", "date_to": "2034-03-21"},
        )


@pytest.mark.asyncio
@respx.mock
async def test_get_timesheets_invalid_date_is_stable_input_error_before_http():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=timesheet_response([])
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(
        ToolInputError, match="YYYY-MM-DD"
    ):
        await mcp.call_tool("get_timesheets", {"date": "2034-02-30"})

    assert not route.called
