"""E2E mock tests for Stage 81 convenience tools.

- get_client_upcoming_visits
- get_daily_schedule
"""

import json
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


def _filter_from(route) -> list[dict]:
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    return json.loads(q["filter"][0])


def _sort_from(route) -> list[dict]:
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    return json.loads(q["sort"][0])


# ── get_client_upcoming_visits ───────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_upcoming_visits_requires_client_id():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_client_upcoming_visits", {"client_id": 0})
    assert "client_id" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_upcoming_visits_builds_filter_with_date_range_and_client():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 2,
                    "admission": [
                        {"id": 1, "status": "accepted", "admission_date": "2026-04-10 10:00:00"},
                        {"id": 3, "status": "directed", "admission_date": "2026-04-12 09:00:00"},
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_client_upcoming_visits",
            {"client_id": 42, "date_from": "2026-04-08", "days": 30},
        )
    data = result.structured_content
    assert data["data"]["totalCount"] == 2
    assert {a["id"] for a in data["data"]["admission"]} == {1, 3}

    filters = _filter_from(route)
    props = {f["property"] for f in filters}
    assert "client_id" in props
    assert "status" in props  # API-level status IN filter
    status_filter = next(f for f in filters if f["property"] == "status")
    assert status_filter["operator"].upper() == "IN"
    assert "accepted" in status_filter["value"]
    assert "deleted" not in status_filter["value"]
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    assert {f["operator"] for f in date_filters} == {">=", "<"}

    sort = _sort_from(route)
    assert sort == [{"property": "admission_date", "direction": "ASC"}]


@pytest.mark.asyncio
@respx.mock
async def test_upcoming_visits_pet_id_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"totalCount": 0, "admission": []}}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_client_upcoming_visits",
            {"client_id": 42, "pet_id": 7},
        )
    filters = _filter_from(route)
    # pet_id maps to patient_id on admission entity
    patient = [f for f in filters if f["property"] == "patient_id"]
    assert patient and patient[0]["value"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_upcoming_visits_relative_date():
    from datetime import date, timedelta

    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"totalCount": 0, "admission": []}}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_client_upcoming_visits",
            {"client_id": 42, "date_from": "today", "days": 7},
        )
    filters = _filter_from(route)
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    gte = [f for f in date_filters if f["operator"] == ">="][0]
    assert gte["value"].startswith(date.today().isoformat())


@pytest.mark.asyncio
@respx.mock
async def test_upcoming_visits_bad_days_rejected():
    billing_mock()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception):
            await mcp.call_tool(
                "get_client_upcoming_visits", {"client_id": 42, "days": 0}
            )


# ── get_daily_schedule ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_daily_schedule_default_today():
    from datetime import date

    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"totalCount": 0, "admission": []}}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_daily_schedule", {})
    data = result.structured_content
    assert data["date"] == date.today().isoformat()

    sort = _sort_from(route)
    assert sort == [{"property": "admission_date", "direction": "ASC"}]

    filters = _filter_from(route)
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    assert {f["operator"] for f in date_filters} == {">=", "<"}


@pytest.mark.asyncio
@respx.mock
async def test_daily_schedule_doctor_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"totalCount": 0, "admission": []}}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_daily_schedule",
            {"date": "2026-04-10", "doctor_id": 5, "clinic_id": 2},
        )
    filters = _filter_from(route)
    props = {f["property"]: f["value"] for f in filters}
    assert props.get("user_id") == 5
    assert props.get("clinic_id") == 2


@pytest.mark.asyncio
@respx.mock
async def test_daily_schedule_filters_inactive_statuses_via_api():
    """API-level status IN filter means the response already excludes inactive."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 2,
                    "admission": [
                        {"id": 1, "status": "accepted"},
                        {"id": 4, "status": "save"},
                    ],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_daily_schedule", {"date": "2026-04-10"})
    data = result.structured_content
    ids = {a["id"] for a in data["data"]["admission"]}
    assert ids == {1, 4}

    # Verify the outgoing filter contains status IN [active statuses].
    filters = _filter_from(route)
    status_filter = next(f for f in filters if f["property"] == "status")
    assert status_filter["operator"].upper() == "IN"
    assert set(status_filter["value"]) >= {"save", "accepted", "directed"}
    assert "deleted" not in status_filter["value"]
    assert "not_approved" not in status_filter["value"]


@pytest.mark.asyncio
@respx.mock
async def test_daily_schedule_reports_truncation_when_total_exceeds_returned_rows():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200,
            json={
                "success": True,
                "data": {
                    "totalCount": 150,
                    "admission": [{"id": index} for index in range(100)],
                },
            },
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_daily_schedule",
            {"date": "2026-04-10", "limit": 100},
        )

    data = result.structured_content
    assert data["returnedCount"] == 100
    assert data["totalCount"] == 150
    assert data["truncated"] is True


@pytest.mark.asyncio
@respx.mock
async def test_daily_schedule_tomorrow_relative():
    from datetime import date, timedelta

    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(
            200, json={"success": True, "data": {"totalCount": 0, "admission": []}}
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_daily_schedule", {"date": "tomorrow"})
    data = result.structured_content
    assert data["date"] == (date.today() + timedelta(days=1)).isoformat()
