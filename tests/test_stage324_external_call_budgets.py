"""Stage 324 regression guards for bounded client search and GET retries."""

from __future__ import annotations

import asyncio
import gc
import warnings
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

import tools.client as client_module
import vetmanager_client as vm_client_module
from exceptions import ToolInputError, VetmanagerError, VetmanagerTimeoutError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient, force_breaker_open, get_breaker_state


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def _runtime_patch():
    return patch_runtime_credentials(DOMAIN, API_KEY, bearer_token="mock-token")


@pytest.mark.asyncio
async def test_name_search_rejects_more_than_four_unique_tokens_before_io(monkeypatch):
    called = False

    async def fake_crud_list(*_args, **_kwargs):
        nonlocal called
        called = True
        return {"success": True, "data": {"client": [], "totalCount": 0}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolInputError, match="at most 4"):
            await mcp.call_tool("get_clients", {"name": "one two three four five"})
    assert called is False


@pytest.mark.asyncio
async def test_name_search_never_runs_more_than_four_calls_concurrently(monkeypatch):
    in_flight = 0
    peak = 0
    calls = 0
    release = asyncio.Event()

    async def fake_crud_list(*_args, **_kwargs):
        nonlocal in_flight, peak, calls
        calls += 1
        in_flight += 1
        peak = max(peak, in_flight)
        await release.wait()
        in_flight -= 1
        return {"success": True, "data": {"client": [], "totalCount": 0}}

    monkeypatch.setattr(client_module, "crud_list", fake_crud_list)
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        task = asyncio.create_task(mcp.call_tool("get_clients", {"name": "one two three four"}))
        while calls < 4:
            await asyncio.sleep(0)
        try:
            assert peak == 4
        finally:
            release.set()
        result = await task

    assert calls == 12
    assert peak == 4
    assert result.structured_content["data"]["totalCount"] == 0


@pytest.mark.asyncio
async def test_bounded_name_search_closes_coroutines_cancelled_before_they_start():
    started = asyncio.Event()
    fail = asyncio.Event()

    async def first():
        started.set()
        await fail.wait()
        raise RuntimeError("upstream failed")

    async def queued():
        await asyncio.Event().wait()

    old_limit = client_module._NAME_SEARCH_CONCURRENCY
    client_module._NAME_SEARCH_CONCURRENCY = 1
    try:
        task = asyncio.create_task(client_module._gather_name_search_requests(first(), queued()))
        await started.wait()
        await asyncio.sleep(0)
        fail.set()
        with pytest.raises(RuntimeError, match="upstream failed"):
            await task
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            gc.collect()
        assert not [warning for warning in caught if issubclass(warning.category, RuntimeWarning)]
    finally:
        client_module._NAME_SEARCH_CONCURRENCY = old_limit


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


@pytest.mark.asyncio
@respx.mock
async def test_retry_after_beyond_budget_does_not_sleep_or_mask_http_status(monkeypatch):
    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "300"})
    )
    sleep = AsyncMock()
    monkeypatch.setattr(vm_client_module, "READ_REQUEST_BUDGET_SECONDS", 1.0)
    monkeypatch.setattr(vm_client_module.asyncio, "sleep", sleep)
    monkeypatch.setattr(vm_client_module, "_backoff_seconds", lambda *_args: 123.456)

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerError) as raised:
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})

    assert raised.value.status_code == 429
    assert route.call_count == 1
    assert all(call.args != (123.456,) for call in sleep.await_args_list)


@pytest.mark.asyncio
async def test_exhausted_read_budget_starts_no_http_attempt(monkeypatch):
    request = AsyncMock()
    client = type("Client", (), {"request": request})()
    monkeypatch.setattr(vm_client_module, "READ_REQUEST_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(vm_client_module, "_get_shared_http_client", AsyncMock(return_value=client))
    monkeypatch.setattr(vm_client_module, "resolve_vetmanager_host", AsyncMock(return_value=BASE))

    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerTimeoutError, match="time budget"):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})

    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_half_open_probe_budget_exhaustion_records_failure_and_releases_probe(monkeypatch):
    """A local GET budget expiry must settle an admitted HALF_OPEN probe."""
    domain = "stage324-budget-half-open"
    base = f"https://{domain}.vetmanager.cloud"
    monkeypatch.setattr(vm_client_module, "READ_REQUEST_BUDGET_SECONDS", 0.0)
    monkeypatch.setattr(vm_client_module, "resolve_vetmanager_host", AsyncMock(return_value=base))
    await force_breaker_open(domain, cooldown_elapsed=True)

    headers_patch, runtime_patch = patch_runtime_credentials(
        domain, API_KEY, bearer_token="mock-token"
    )
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerTimeoutError, match="time budget"):
            await VetmanagerClient().get("/rest/api/client", params={"limit": 1})

    state = get_breaker_state(domain)
    assert state is not None
    assert state["state"] == "open"
    assert state["probe_in_flight"] is False
