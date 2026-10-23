"""Stage 403: one GET budget covers resolution, retries and transfer."""

import asyncio
import time
from unittest.mock import AsyncMock

import pytest
import httpx
from fastmcp.exceptions import ToolError

import vetmanager_client as vm
import host_resolver
from exceptions import VetmanagerTimeoutError
from server import mcp
from service_metrics import snapshot_service_metrics
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "stage403-deadline"
BASE = f"https://{DOMAIN}.vetmanager.cloud"


def _runtime():
    return patch_runtime_credentials(DOMAIN, "mock-api-key", bearer_token="mock-token")


@pytest.mark.asyncio
async def test_get_deadline_includes_host_resolution(monkeypatch):
    request = AsyncMock()
    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr(vm, "_get_shared_http_client", AsyncMock(return_value=type("C", (), {"request": request})()))

    async def slow_resolution(*_args, **_kwargs):
        await asyncio.sleep(0.2)
        return BASE

    monkeypatch.setattr(vm, "resolve_vetmanager_host", slow_resolution)
    headers, runtime = _runtime()
    with headers, runtime:
        with pytest.raises(VetmanagerTimeoutError, match="time budget"):
            await asyncio.wait_for(vm.VetmanagerClient().get("/rest/api/client/1"), 0.15)
    request.assert_not_awaited()


@pytest.mark.asyncio
async def test_get_deadline_stops_slow_progress_and_does_not_trip_closed_breaker(monkeypatch):
    calls = 0

    async def slow_progress(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        while True:
            await asyncio.sleep(0.01)  # Continuous progress can evade phase read timeout.

    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 0.04)
    monkeypatch.setattr(vm, "REQUEST_GAP_SECONDS", 0.0)
    monkeypatch.setattr(vm, "_READ_REQUEST_MIN_REMAINING_SECONDS", 0.001)
    monkeypatch.setattr(vm, "resolve_vetmanager_host", AsyncMock(return_value=BASE))
    monkeypatch.setattr(vm, "_get_shared_http_client", AsyncMock(return_value=type("C", (), {"request": slow_progress})()))
    headers, runtime = _runtime()
    with headers, runtime:
        started = time.monotonic()
        with pytest.raises(VetmanagerTimeoutError, match="time budget"):
            await asyncio.wait_for(vm.VetmanagerClient().get("/rest/api/client/1"), 0.2)
    assert time.monotonic() - started < 0.15
    assert calls == 1
    state = vm.get_breaker_state(DOMAIN)
    assert state["state"] == "closed"
    assert state["consecutive_failures"] == 0


@pytest.mark.asyncio
async def test_deadline_releases_half_open_probe(monkeypatch):
    async def never_complete(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr(vm, "REQUEST_GAP_SECONDS", 0.0)
    monkeypatch.setattr(vm, "_READ_REQUEST_MIN_REMAINING_SECONDS", 0.001)
    monkeypatch.setattr(vm, "resolve_vetmanager_host", AsyncMock(return_value=BASE))
    monkeypatch.setattr(vm, "_get_shared_http_client", AsyncMock(return_value=type("C", (), {"request": never_complete})()))
    await vm.force_breaker_open(DOMAIN, cooldown_elapsed=True)
    headers, runtime = _runtime()
    with headers, runtime:
        with pytest.raises(VetmanagerTimeoutError, match="time budget"):
            await asyncio.wait_for(vm.VetmanagerClient().get("/rest/api/client/1"), 0.2)
    state = vm.get_breaker_state(DOMAIN)
    assert state["state"] == "open"
    assert state["probe_in_flight"] is False


@pytest.mark.asyncio
async def test_external_cancellation_remains_cancellation(monkeypatch):
    started = asyncio.Event()

    async def wait_forever(*_args, **_kwargs):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 1.0)
    monkeypatch.setattr(vm, "resolve_vetmanager_host", AsyncMock(return_value=BASE))
    monkeypatch.setattr(vm, "_get_shared_http_client", AsyncMock(return_value=type("C", (), {"request": wait_forever})()))
    headers, runtime = _runtime()
    with headers, runtime:
        task = asyncio.create_task(vm.VetmanagerClient().get("/rest/api/client/1"))
        await asyncio.wait_for(started.wait(), 0.2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_cancelled_resolution_waiter_does_not_cancel_shared_lookup(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def shared_lookup(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return BASE

    monkeypatch.setattr(host_resolver, "_resolve_vetmanager_host_uncached", shared_lookup)
    first = asyncio.create_task(host_resolver.resolve_vetmanager_host(DOMAIN))
    await asyncio.wait_for(started.wait(), 0.2)
    second = asyncio.create_task(host_resolver.resolve_vetmanager_host(DOMAIN))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    release.set()
    assert await asyncio.wait_for(second, 0.2) == BASE
    assert calls == 1


@pytest.mark.asyncio
async def test_retry_disabled_get_keeps_phase_timeout_contract(monkeypatch):
    async def short_request(*_args, **_kwargs):
        await asyncio.sleep(0.04)
        return httpx.Response(200, json={"success": True})

    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 0.02)
    monkeypatch.setattr(vm, "REQUEST_GAP_SECONDS", 0.0)
    monkeypatch.setattr(vm, "resolve_vetmanager_host", AsyncMock(return_value=BASE))
    monkeypatch.setattr(vm, "_get_shared_http_client", AsyncMock(return_value=type("C", (), {"request": short_request})()))
    headers, runtime = _runtime()
    with headers, runtime:
        result = await vm.VetmanagerClient().get("/rest/api/client/1", retry=False)
    assert result == {"success": True}


@pytest.mark.asyncio
async def test_deadline_is_counted_as_dated_cards_timeout(monkeypatch):
    async def slow_resolution(*_args, **_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(vm, "READ_REQUEST_BUDGET_SECONDS", 0.03)
    monkeypatch.setattr(vm, "resolve_vetmanager_host", slow_resolution)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError, match="timed out"):
        await asyncio.wait_for(mcp.call_tool("get_medical_cards_by_date", {
            "date": "2026-10-22", "limit": 1,
        }), 0.2)
    label = "/rest/api/MedicalCards#list:get_medical_cards_by_date|GET|timeout"
    assert snapshot_service_metrics()["tool_calls_total"][label] == 1
