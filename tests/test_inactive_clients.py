"""Tests for get_inactive_clients tool."""

import json

import pytest
import respx
import httpx

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


def _client_response(clients):
    return httpx.Response(200, json={"data": {"totalCount": len(clients), "client": clients}})


def _make_clients(n, base_id=1):
    return [
        {
            "id": base_id + i,
            "last_name": f"Doe{base_id + i}",
            "first_name": "John",
            "middle_name": "",
            "cell_phone": f"+10000000{base_id + i:03d}",
            "last_visit_date": f"2024-{(i % 12) + 1:02d}-15 10:00:00",
            "status": "ACTIVE",
        }
        for i in range(n)
    ]


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_clients_returns_clients_in_window():
    billing_mock()
    clients = _make_clients(3)
    respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response(clients))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_inactive_clients", {})

    data = json.loads(result.content[0].text)
    assert data["months_min"] == 13
    assert data["months_max"] == 24
    assert data["limit_applied"] == 50
    assert len(data["inactive_clients"]) == 3
    assert data["inactive_clients"][0]["id"] == 1
    assert "cutoff_window" in data
    assert "from" in data["cutoff_window"]
    assert "to" in data["cutoff_window"]


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_clients_respects_custom_window_and_limit():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response(_make_clients(5)))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(
            "get_inactive_clients",
            {"months_min": 6, "months_max": 12, "limit": 5},
        )

    data = json.loads(result.content[0].text)
    assert data["months_min"] == 6
    assert data["months_max"] == 12
    assert data["limit_applied"] == 5


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_clients_sends_status_active_and_last_visit_date_filters():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_clients", {})

    request = route.calls.last.request
    filter_param = request.url.params.get("filter", "")
    assert '"status"' in filter_param
    assert '"ACTIVE"' in filter_param
    assert '"last_visit_date"' in filter_param
    assert '">="' in filter_param
    assert '"<="' in filter_param


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_clients_sorts_by_last_visit_date_desc():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_clients", {})

    request = route.calls.last.request
    sort_param = request.url.params.get("sort", "")
    assert '"last_visit_date"' in sort_param
    assert '"DESC"' in sort_param


@pytest.mark.asyncio
@respx.mock
async def test_get_inactive_clients_limit_50_default_in_api_call():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(return_value=_client_response([]))

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_inactive_clients", {})

    request = route.calls.last.request
    assert request.url.params.get("limit") == "50"
