"""Stage 443: bounded billing retry and terminal resolution timeout signal."""

import asyncio

import httpx
import pytest
import respx

import host_resolver
import vetmanager_client
from exceptions import VetmanagerTimeoutError
from service_metrics import snapshot_service_metrics
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient


@pytest.mark.asyncio
@respx.mock
async def test_billing_read_timeout_retries_once_then_resolves():
    domain = "stage443retry"
    origin = f"https://{domain}.vetmanager2.ru"
    calls = 0

    def respond(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("first lookup")
        return httpx.Response(200, json={"url": origin})

    primary = respx.get(f"https://billing-api.vetmanager.cloud/host/{domain}").mock(side_effect=respond)
    alias = respx.get(f"https://billing-api.vetmanager.ru/host/{domain}").mock(return_value=httpx.Response(200, json={"url": origin}))
    assert await host_resolver.resolve_vetmanager_host(domain) == origin
    assert primary.call_count == 2
    assert alias.call_count == 0


@pytest.mark.asyncio
async def test_terminal_resolution_timeout_is_counted(monkeypatch):
    async def fail(_self):
        raise VetmanagerTimeoutError("Timeout resolving Vetmanager host.")

    monkeypatch.setattr(VetmanagerClient, "_resolve_host", fail)
    headers, runtime = patch_runtime_credentials("stage443terminal", "mock-key", bearer_token="mock-token")
    with headers, runtime, pytest.raises(VetmanagerTimeoutError):
        await VetmanagerClient().get("/rest/api/MedicalCards")
    assert snapshot_service_metrics()["upstream_failures_total"]["host_resolution|timeout"] == 1


@pytest.mark.asyncio
async def test_get_budget_expires_during_resolution_but_caller_cancel_does_not(monkeypatch):
    async def slow(_self):
        await asyncio.sleep(1)
        return "https://stage443budget.vetmanager2.ru"

    monkeypatch.setattr(VetmanagerClient, "_resolve_host", slow)
    monkeypatch.setattr(vetmanager_client, "READ_REQUEST_BUDGET_SECONDS", 0.01)
    headers, runtime = patch_runtime_credentials("stage443budget", "mock-key", bearer_token="mock-token")
    with headers, runtime:
        with pytest.raises(VetmanagerTimeoutError):
            await VetmanagerClient().get("/rest/api/MedicalCards")
    assert snapshot_service_metrics()["upstream_failures_total"]["host_resolution|timeout"] == 1

    monkeypatch.setattr(vetmanager_client, "READ_REQUEST_BUDGET_SECONDS", 30.0)
    with headers, runtime:
        task = asyncio.create_task(VetmanagerClient().get("/rest/api/MedicalCards"))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert snapshot_service_metrics()["upstream_failures_total"]["host_resolution|timeout"] == 1
