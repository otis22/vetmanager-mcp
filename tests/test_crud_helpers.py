"""Unit tests for tools/crud_helpers.py."""

import pytest
import respx
import httpx

from tests.runtime_factories import patch_runtime_credentials
from tools.crud_helpers import (
    crud_list,
    crud_get_by_id,
    crud_create,
    crud_update,
    crud_delete,
    paginate_all,
)

DOMAIN = "testclinic"
API_KEY = "test-key-helpers"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


from contextlib import contextmanager

@contextmanager
def bearer_patch():
    headers_p, runtime_p = patch_runtime_credentials(
        DOMAIN, API_KEY, bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers_p, runtime_p:
        yield


# ── crud_list ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_list_builds_params_and_calls_get():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/breed").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    with bearer_patch():
        result = await crud_list(
            "/rest/api/breed", limit=10, offset=0,
            sort=[{"property": "title", "direction": "ASC"}],
        )
    assert route.called
    assert result == {"data": [{"id": 1}]}
    req = route.calls[0].request
    assert "limit=10" in str(req.url)
    assert "sort=" in str(req.url)


@pytest.mark.asyncio
@respx.mock
async def test_crud_list_with_extra_params():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    with bearer_patch():
        await crud_list(
            "/rest/api/pet", limit=20, offset=0,
            extra={"client_id": 42},
        )
    assert "client_id=42" in str(route.calls[0].request.url)


# ── crud_get_by_id ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_get_by_id_constructs_url():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/breed/99").mock(
        return_value=httpx.Response(200, json={"data": {"id": 99}})
    )
    with bearer_patch():
        result = await crud_get_by_id("/rest/api/breed", 99)
    assert route.called
    assert result == {"data": {"id": 99}}


# ── crud_create ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_create_posts_payload():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}})
    )
    with bearer_patch():
        result = await crud_create("/rest/api/client", {"firstName": "Anna"})
    assert route.called
    assert result == {"data": {"id": 1}}


# ── crud_update ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_update_puts_payload():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/client/5").mock(
        return_value=httpx.Response(200, json={"data": {"id": 5}})
    )
    with bearer_patch():
        result = await crud_update("/rest/api/client", 5, {"first_name": "Bob"})
    assert route.called
    assert result == {"data": {"id": 5}}


# ── crud_delete ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_delete_calls_delete():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/client/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    with bearer_patch():
        result = await crud_delete("/rest/api/client", 7)
    assert route.called
    assert result == {"data": {"id": 7}}


# ── paginate_all ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_single_page():
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": 2, "client": [{"id": 1}, {"id": 2}]}
        })
    )
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=100,
        )
    assert total == 2
    assert len(records) == 2


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_multi_page():
    billing_mock()
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={
                "data": {"totalCount": 3, "item": [{"id": 1}, {"id": 2}]}
            })
        return httpx.Response(200, json={
            "data": {"totalCount": 3, "item": [{"id": 3}]}
        })

    respx.get(f"{BASE}/rest/api/item").mock(side_effect=side_effect)
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/item", entity_key="item", page_size=2,
        )
    assert total == 3
    assert len(records) == 3
    assert call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_empty():
    billing_mock()
    respx.get(f"{BASE}/rest/api/invoice").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": 0, "invoice": []}
        })
    )
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/invoice", entity_key="invoice",
        )
    assert total == 0
    assert records == []


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_with_filters():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": 1, "client": [{"id": 1, "status": "ACTIVE"}]}
        })
    )
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/client",
            filters=[{"property": "status", "value": "ACTIVE", "operator": "="}],
            entity_key="client",
        )
    assert total == 1
    assert len(records) == 1
    assert "filter=" in str(route.calls[0].request.url)


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_boundary_100_stops_on_first_page():
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={
            "data": {"totalCount": 100, "client": [{"id": i} for i in range(100)]}
        })
    )
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=100,
        )
    assert total == 100
    assert len(records) == 100
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_paginate_all_boundary_101_fetches_second_page_and_keeps_initial_total():
    billing_mock()
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return httpx.Response(200, json={
                "data": {"totalCount": 101, "client": [{"id": i} for i in range(100)]}
            })
        return httpx.Response(200, json={
            "data": {"totalCount": 9999, "client": [{"id": 100}]}
        })

    respx.get(f"{BASE}/rest/api/client").mock(side_effect=side_effect)
    with bearer_patch():
        records, total = await paginate_all(
            "/rest/api/client", entity_key="client", page_size=100,
        )
    assert total == 101
    assert len(records) == 101
    assert call_count == 2
