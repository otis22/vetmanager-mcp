"""Tests for Stage 78 — LLM-friendly named filter parameters.

Each new filter param must:
- be reflected in the outgoing `filter` query string;
- leave existing positional behavior untouched;
- reject invalid inputs with ValueError.
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


def _filter_from_request(route) -> list[dict]:
    """Extract and JSON-parse the `filter` query param from the last request."""
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    assert "filter" in q, f"no filter param in {url}"
    return json.loads(q["filter"][0])


# ── get_pets.alias ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_pets_alias_requires_owner_id():
    billing_mock()
    respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_pets", {"alias": "Барсик"})
    # FastMCP may wrap ValueError in ToolError; either way the message surfaces.
    assert "owner_id" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_pets_alias_with_owner_id_builds_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 7, "alias": "Барсик"}]})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_pets", {"owner_id": 42, "alias": "Барсик"})
    assert route.called
    filters = _filter_from_request(route)
    props = {(f["property"], f.get("operator", "").upper()) for f in filters}
    assert ("owner_id", "=") in props
    assert ("alias", "LIKE") in props


@pytest.mark.asyncio
@respx.mock
async def test_get_pets_owner_only_unchanged():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_pets", {"owner_id": 42})
    assert route.called
    filters = _filter_from_request(route)
    assert len(filters) == 1
    assert filters[0]["property"] == "owner_id"


# ── get_clients.phone / email ────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_clients_phone_normalized():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_clients", {"phone": "+7 (916) 123-45-67"})
    filters = _filter_from_request(route)
    phone_filters = [f for f in filters if f["property"] == "cell_phone"]
    assert len(phone_filters) == 1
    assert phone_filters[0]["value"] == "79161234567"
    assert phone_filters[0]["operator"].upper() == "LIKE"


@pytest.mark.asyncio
@respx.mock
async def test_get_clients_phone_too_short_rejected():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_clients", {"phone": "12"})
    assert "4 digits" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_clients_email_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_clients", {"email": "ivan@example.com"})
    filters = _filter_from_request(route)
    email_filters = [f for f in filters if f["property"] == "email"]
    assert email_filters and email_filters[0]["value"] == "ivan@example.com"


# ── get_users.name / position_id / is_active ─────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_users_name_filter_merges_last_and_first_name():
    """name search issues two requests (last_name OR first_name) and merges."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"user": [{"id": 7, "last_name": "Иванова"}]}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_users", {"name": "Иванова"})
    # Two requests total: one for last_name, one for first_name.
    assert len(route.calls) == 2
    call_props: list[set] = []
    for call in route.calls:
        q = parse_qs(urlparse(str(call.request.url)).query)
        fs = json.loads(q["filter"][0])
        call_props.append({f["property"] for f in fs})
    # Each call should have exactly one of last_name/first_name filters set.
    assert any("last_name" in p for p in call_props)
    assert any("first_name" in p for p in call_props)


@pytest.mark.asyncio
@respx.mock
async def test_get_users_is_active_default_true():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_users", {})
    filters = _filter_from_request(route)
    active = [f for f in filters if f["property"] == "is_active"]
    assert active and active[0]["value"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_users_is_active_false_filters_inactive_only():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_users", {"is_active": False})
    filters = _filter_from_request(route)
    act = [f for f in filters if f["property"] == "is_active"]
    assert act and act[0]["value"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_get_users_is_active_none_no_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_users", {"is_active": None})
    url = str(route.calls.last.request.url)
    q = parse_qs(urlparse(url).query)
    # Either no filter at all, or filter without is_active property.
    if "filter" in q:
        filters = json.loads(q["filter"][0])
        assert all(f["property"] != "is_active" for f in filters)


@pytest.mark.asyncio
@respx.mock
async def test_get_users_position_id_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_users", {"position_id": 7})
    filters = _filter_from_request(route)
    pos = [f for f in filters if f["property"] == "position_id"]
    assert pos and pos[0]["value"] == 7


# ── get_admissions date_from/to, doctor_id, pet_id, client_id ────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_date_range_uses_gte_lt_next_day():
    """date_to uses strict `<` against next day's midnight for fractional-second safety."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_admissions",
            {"date_from": "2026-04-01", "date_to": "2026-04-08"},
        )
    filters = _filter_from_request(route)
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    ops = {f["operator"] for f in date_filters}
    assert ops == {">=", "<"}
    gte = [f for f in date_filters if f["operator"] == ">="][0]
    lt = [f for f in date_filters if f["operator"] == "<"][0]
    assert gte["value"] == "2026-04-01 00:00:00"
    assert lt["value"] == "2026-04-09 00:00:00"  # next day midnight


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_single_date_back_compat():
    """`date` alone expands to the same >=/< pair as date_from=date_to=<date>."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_admissions", {"date": "2026-04-08"})
    filters = _filter_from_request(route)
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    assert len(date_filters) == 2
    assert {f["operator"] for f in date_filters} == {">=", "<"}


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_invalid_date_rejected():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_admissions", {"date_to": "04/08/2026"})
    assert "Supported formats" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_date_and_range_rejected():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_admissions",
                {"date": "2026-04-08", "date_from": "2026-04-01"},
            )
    assert "date_from" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_doctor_pet_client_ids():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_admissions",
            {"doctor_id": 3, "pet_id": 5, "client_id": 42},
        )
    filters = _filter_from_request(route)
    props = {f["property"]: f["value"] for f in filters}
    # doctor_id maps to user_id, pet_id maps to patient_id
    assert props.get("user_id") == 3
    assert props.get("patient_id") == 5
    assert props.get("client_id") == 42


# ── get_goods title / group_id / is_active ───────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_goods_title_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_goods", {"title": "Amoxicillin"})
    filters = _filter_from_request(route)
    title_filters = [f for f in filters if f["property"] == "title"]
    assert title_filters and title_filters[0]["value"] == "Amoxicillin"
    assert title_filters[0]["operator"].upper() == "LIKE"


@pytest.mark.asyncio
@respx.mock
async def test_get_goods_is_active_true():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_goods", {"is_active": True})
    filters = _filter_from_request(route)
    act = [f for f in filters if f["property"] == "is_active"]
    assert act and act[0]["value"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_goods_group_id():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_goods", {"group_id": 4})
    filters = _filter_from_request(route)
    grp = [f for f in filters if f["property"] == "group_id"]
    assert grp and grp[0]["value"] == 4


# ── get_invoices payment_status / pet_id ─────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_invoices_payment_status_valid():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_invoices", {"payment_status": "none"})
    filters = _filter_from_request(route)
    ps = [f for f in filters if f["property"] == "payment_status"]
    assert ps and ps[0]["value"] == "none"


@pytest.mark.asyncio
@respx.mock
async def test_get_invoices_payment_status_invalid():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_invoices", {"payment_status": "paid"})
    assert "payment_status" in str(exc_info.value)


# ── filter composition with user-supplied filter[] ──────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_pets_user_filter_preserved_with_alias():
    """User-supplied filter[] must be preserved alongside named alias filter."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_pets",
            {
                "owner_id": 42,
                "alias": "Барсик",
                "filter": [
                    {"property": "type_id", "value": 3, "operator": "="}
                ],
            },
        )
    filters = _filter_from_request(route)
    props = {f["property"] for f in filters}
    # Original user filter + owner_id + alias all present.
    assert props == {"type_id", "owner_id", "alias"}


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_user_filter_preserved_with_named_params():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_admissions",
            {
                "doctor_id": 3,
                "date_from": "2026-04-01",
                "date_to": "2026-04-08",
                "filter": [
                    {"property": "clinic_id", "value": 1, "operator": "="}
                ],
            },
        )
    filters = _filter_from_request(route)
    props = [f["property"] for f in filters]
    assert "clinic_id" in props
    assert "user_id" in props
    assert props.count("admission_date") == 2


# ── Stage 79: relative dates in date params ─────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_relative_dates_resolved():
    """date_from='today', date_to='+7d' must resolve to absolute dates in filter."""
    from datetime import date, timedelta
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_admissions",
            {"date_from": "today", "date_to": "+7d"},
        )
    filters = _filter_from_request(route)
    date_filters = [f for f in filters if f["property"] == "admission_date"]
    assert len(date_filters) == 2
    today = date.today()
    # Expected: >= today 00:00:00, < (today + 8 days) 00:00:00
    expected_end = (today + timedelta(days=8)).isoformat()
    gte = [f for f in date_filters if f["operator"] == ">="][0]
    lt = [f for f in date_filters if f["operator"] == "<"][0]
    assert gte["value"].startswith(today.isoformat())
    assert lt["value"].startswith(expected_end)


@pytest.mark.asyncio
@respx.mock
async def test_get_invoices_relative_dates():
    from datetime import date, timedelta
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_invoices",
            {"date_from": "-30d", "date_to": "today"},
        )
    filters = _filter_from_request(route)
    date_filters = [f for f in filters if f["property"] == "create_date"]
    assert len(date_filters) == 2
    today = date.today()
    thirty_ago = (today - timedelta(days=30)).isoformat()
    by_op = {f["operator"]: f["value"] for f in date_filters}
    assert by_op[">="] == thirty_ago
    assert by_op["<="] == today.isoformat()


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_invalid_relative_date_rejected():
    billing_mock()
    respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool("get_admissions", {"date_from": "next_week"})
    assert "Supported formats" in str(exc_info.value) or "invalid" in str(exc_info.value).lower()


@pytest.mark.asyncio
@respx.mock
async def test_get_invoices_pet_id_filter():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_invoices", {"pet_id": 7})
    filters = _filter_from_request(route)
    pet = [f for f in filters if f["property"] == "pet_id"]
    assert pet and pet[0]["value"] == 7
