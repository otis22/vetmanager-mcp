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


def _query_from_call(call) -> dict[str, list[str]]:
    return parse_qs(urlparse(str(call.request.url)).query)


def _filters_from_call(call) -> list[dict]:
    query = _query_from_call(call)
    assert "filter" in query, f"no filter param in {call.request.url}"
    return json.loads(query["filter"][0])


def _sort_from_call(call) -> list[dict]:
    query = _query_from_call(call)
    assert "sort" in query, f"no sort param in {call.request.url}"
    return json.loads(query["sort"][0])


@pytest.mark.asyncio
@respx.mock
async def test_get_debtors_uses_server_side_balance_filter_and_stable_page():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "totalCount": 2,
                    "client": [
                        {
                            "id": 1,
                            "last_name": "Ivanov",
                            "first_name": "Ivan",
                            "balance": "-500.00",
                            "status": "ACTIVE",
                            "last_visit_date": "2026-06-01 10:00:00",
                        },
                        {
                            "id": 2,
                            "last_name": "FilteredOut",
                            "balance": "100.00",
                            "status": "ACTIVE",
                        },
                    ],
                }
            },
        )
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_debtors", {"limit": 50, "offset": 100})

    query = _query_from_call(route.calls[0])
    assert query["limit"] == ["50"]
    assert query["offset"] == ["100"]
    filters = _filters_from_call(route.calls[0])
    actual = {(f["property"], f["operator"], f["value"]) for f in filters}
    assert ("status", "=", "ACTIVE") in actual
    assert ("balance", "<", "0") in actual
    assert _sort_from_call(route.calls[0]) == [{"property": "id", "direction": "ASC"}]

    data = result.structured_content
    assert data["server_side_balance_filter"] is True
    assert data["returned_count"] == 1
    assert data["debtors_count"] == 1
    assert data["total_count"] == 2
    assert data["total_active_clients_checked"] == 2
    assert data["limit"] == 50
    assert data["offset"] == 100
    assert data["debtors"][0]["id"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_debtors_adds_last_visit_date_window_filters():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "client": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_debtors",
            {
                "last_visit_date_from": "2026-01-01",
                "last_visit_date_to": "2026-06-17",
            },
        )

    actual = {(f["property"], f["operator"], f["value"]) for f in _filters_from_call(route.calls[0])}
    assert ("last_visit_date", ">=", "2026-01-01") in actual
    assert ("last_visit_date", "<=", "2026-06-17") in actual


@pytest.mark.asyncio
@respx.mock
async def test_get_debtors_rejects_inverted_last_visit_window_before_http():
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 0, "client": []}})
    )

    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(Exception) as exc_info:
            await mcp.call_tool(
                "get_debtors",
                {
                    "last_visit_date_from": "2026-06-17",
                    "last_visit_date_to": "2026-01-01",
                },
            )

    assert "last_visit_date_from" in str(exc_info.value)
    assert not route.called
