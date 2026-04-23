"""E2E mock tests for get_doctor_free_slots (Stage 80)."""

import asyncio
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

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
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


# ── Validation errors ────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_missing_doctor_id_rejected():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_doctor_free_slots", {"doctor_id": 0})
    assert "doctor_id" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_range_over_31_days_rejected():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_doctor_free_slots",
                {
                    "doctor_id": 1,
                    "date_from": "2026-04-01",
                    "date_to": "2026-05-15",
                },
            )
    assert "31 days" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_reversed_range_rejected():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_doctor_free_slots",
                {
                    "doctor_id": 1,
                    "date_from": "2026-04-10",
                    "date_to": "2026-04-01",
                },
            )
    assert ">= date_from" in str(exc_info.value) or "date_to" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_bad_slot_minutes_rejected():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_doctor_free_slots",
                {"doctor_id": 1, "slot_minutes": 1},
            )
    assert "slot_minutes" in str(exc_info.value)


# ── Happy path ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_empty_timesheet_returns_no_slots():
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "timesheet": []}},
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "admission": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
            },
        )
    data = result.structured_content
    assert data["total_slots"] == 0
    assert data["slots"] == []


@pytest.mark.asyncio
@respx.mock
async def test_no_admissions_full_timesheet_chunked():
    """9:00–11:00 work, no admissions, 30-min slots → 4 slots."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 11:00:00",
                            "clinic_id": 1,
                            "all_day": 0,
                            "night": 0,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "admission": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    assert data["total_slots"] == 4
    assert data["slots"][0]["start"] == "2026-04-10T09:00:00"
    assert data["slots"][0]["duration_min"] == 30
    assert data["slots"][-1]["end"] == "2026-04-10T11:00:00"
    assert all(s["clinic_id"] == 1 for s in data["slots"])


@pytest.mark.asyncio
@respx.mock
async def test_admission_blocks_slots():
    """Admission from 10:00 for 30min blocks one slot."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 11:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 10:00:00",
                            "admission_length": "00:30:00",
                            "user_id": 1,
                            "status": "accepted",
                        }
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    # 9:00-10:00 = 2 slots, 10:00-10:30 blocked, 10:30-11:00 = 1 slot → 3 total
    assert data["total_slots"] == 3
    starts = [s["start"] for s in data["slots"]]
    assert "2026-04-10T10:00:00" not in starts  # blocked
    assert "2026-04-10T10:30:00" in starts  # free after admission


@pytest.mark.asyncio
@respx.mock
async def test_deleted_admission_ignored():
    """Deleted/not_approved admissions don't block slots."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 10:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 2,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 09:00:00",
                            "admission_length": "00:30:00",
                            "user_id": 1,
                            "status": "deleted",
                        },
                        {
                            "id": 101,
                            "admission_date": "2026-04-10 09:30:00",
                            "admission_length": "00:30:00",
                            "user_id": 1,
                            "status": "not_approved",
                        },
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    # Both admissions ignored → 2 free slots (9:00 and 9:30)
    assert data["total_slots"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_admission_length_zero_fallback():
    """admission_length='00:00:00' falls back to slot_minutes duration."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 10:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 09:00:00",
                            "admission_length": "00:00:00",
                            "user_id": 1,
                            "status": "accepted",
                        }
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    # Admission at 9:00 for fallback 30min blocks 9:00-9:30 → 1 remaining slot.
    assert data["total_slots"] == 1
    assert data["slots"][0]["start"] == "2026-04-10T09:30:00"


@pytest.mark.asyncio
@respx.mock
async def test_night_shift_slots():
    """Timesheet crossing midnight is treated as one continuous interval."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 22:00:00",
                            "end_datetime": "2026-04-11 00:00:00",
                            "clinic_id": 1,
                            "night": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "admission": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 60,
            },
        )
    data = result.structured_content
    # 22:00-24:00 = 2 hours = 2 slots
    assert data["total_slots"] == 2
    assert data["slots"][0]["start"] == "2026-04-10T22:00:00"
    assert data["slots"][-1]["end"] == "2026-04-11T00:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_long_admission_started_before_window_blocks_slot():
    """Admission 2026-04-10 23:30 + 2h must block 2026-04-11 00:00-01:30."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-11 00:00:00",
                            "end_datetime": "2026-04-11 03:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 23:30:00",
                            "admission_length": "02:00:00",
                            "user_id": 1,
                            "status": "accepted",
                        }
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-11",
                "date_to": "2026-04-11",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    # Admission extends to 01:30 on the 11th. Work is 00:00-03:00.
    # Free = 01:30-03:00 = 3 slots of 30 min.
    assert data["total_slots"] == 3
    assert data["slots"][0]["start"] == "2026-04-11T01:30:00"


@pytest.mark.asyncio
@respx.mock
async def test_admission_ended_before_window_ignored():
    """Admission 2026-04-10 22:00 + 30m ends at 22:30 — must not affect Apr 11."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-11 00:00:00",
                            "end_datetime": "2026-04-11 01:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 22:00:00",
                            "admission_length": "00:30:00",
                            "user_id": 1,
                            "status": "accepted",
                        }
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-11",
                "date_to": "2026-04-11",
                "slot_minutes": 30,
            },
        )
    data = result.structured_content
    # Admission 22:00-22:30 ends before window 00:00 next day → no block.
    assert data["total_slots"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_too_many_rows_raises():
    """paginate_all max_rows guard fires when totalCount exceeds cap."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 99999,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 10:00:00",
                            "clinic_id": 1,
                        }
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "admission": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_doctor_free_slots",
                {
                    "doctor_id": 1,
                    "date_from": "2026-04-10",
                    "date_to": "2026-04-10",
                },
            )
    assert "too large" in str(exc_info.value) or "max_rows" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_filter_contains_doctor_id_and_date_range():
    """Verify the outgoing request filter carries doctor_id and date range."""
    billing_mock()
    ts_route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "timesheet": []}},
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "admission": []}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 42,
                "date_from": "2026-04-10",
                "date_to": "2026-04-12",
            },
        )
    q = parse_qs(urlparse(str(ts_route.calls.last.request.url)).query)
    filters = json.loads(q["filter"][0])
    props = {(f["property"], f["operator"]) for f in filters}
    assert ("doctor_id", "=") in props
    # Must have the begin_datetime upper bound and end_datetime lower bound
    # (overlap semantics: fetch any row whose interval touches the window).
    assert any(f["property"] == "begin_datetime" for f in filters)
    assert any(f["property"] == "end_datetime" for f in filters)


@pytest.mark.asyncio
@respx.mock
async def test_multi_clinic_admission_blocks_only_its_own_clinic():
    """Admission in clinic 1 must not hide the same slot in clinic 2."""
    billing_mock()
    respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 2,
                    "timesheet": [
                        {
                            "id": 1,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 10:00:00",
                            "clinic_id": 1,
                        },
                        {
                            "id": 2,
                            "doctor_id": 1,
                            "begin_datetime": "2026-04-10 09:00:00",
                            "end_datetime": "2026-04-10 10:00:00",
                            "clinic_id": 2,
                        },
                    ],
                },
            },
        )
    )
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 1,
                    "admission": [
                        {
                            "id": 100,
                            "admission_date": "2026-04-10 09:00:00",
                            "admission_length": "01:00:00",
                            "user_id": 1,
                            "clinic_id": 1,
                            "status": "accepted",
                        }
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 60,
            },
        )

    data = result.structured_content
    assert data["total_slots"] == 1
    assert data["slots"][0]["clinic_id"] == 2
    assert data["slots"][0]["start"] == "2026-04-10T09:00:00"


@pytest.mark.asyncio
async def test_schedule_fetches_timesheet_and_admission_in_parallel(monkeypatch):
    """timesheet/admission fetch should overlap, not run serially."""
    import tools.schedule as schedule_module

    async def fake_paginate_all(endpoint, **kwargs):
        await asyncio.sleep(0.05)
        if endpoint == "/rest/api/timesheet":
            return ([{
                "id": 1,
                "doctor_id": 1,
                "begin_datetime": "2026-04-10 09:00:00",
                "end_datetime": "2026-04-10 10:00:00",
                "clinic_id": 1,
            }], 1)
        return ([], 0)

    monkeypatch.setattr(schedule_module, "paginate_all", fake_paginate_all)

    headers_patch, runtime_patch = bearer_runtime_patch()
    started = time.perf_counter()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_doctor_free_slots",
            {
                "doctor_id": 1,
                "date_from": "2026-04-10",
                "date_to": "2026-04-10",
                "slot_minutes": 30,
            },
        )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.09, f"expected parallel fetch, got serial latency {elapsed:.3f}s"
    data = result.structured_content
    assert data["total_slots"] == 2
