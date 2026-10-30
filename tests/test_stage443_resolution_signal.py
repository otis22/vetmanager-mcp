"""Stage 443: bounded billing retry and terminal resolution timeout signal."""

import asyncio

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

import host_resolver
import vetmanager_client
from server import mcp
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
    entered = asyncio.Event()

    async def slow_until_cancel(_self):
        entered.set()
        await asyncio.sleep(1)

    monkeypatch.setattr(VetmanagerClient, "_resolve_host", slow_until_cancel)
    with headers, runtime:
        task = asyncio.create_task(VetmanagerClient().get("/rest/api/MedicalCards"))
        await entered.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert snapshot_service_metrics()["upstream_failures_total"]["host_resolution|timeout"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_all_billing_and_probe_timeouts_count_as_terminal_resolution_timeout():
    domain = "stage443alltimeout"
    for base in (
        "https://billing-api.vetmanager.cloud/host/",
        "https://billing-api.vetmanager.ru/host/",
        f"https://{domain}.vetmanager2.ru/rest/api/user/",
        f"https://{domain}.vetmanager.ru/rest/api/user/",
    ):
        respx.get(base + (domain if "/host/" in base else "1")).mock(
            side_effect=httpx.ReadTimeout("timed out")
        )
    headers, runtime = patch_runtime_credentials(domain, "mock-key", bearer_token="mock-token")
    with headers, runtime, pytest.raises(VetmanagerTimeoutError):
        await VetmanagerClient().get("/rest/api/MedicalCards")
    assert snapshot_service_metrics()["upstream_failures_total"]["host_resolution|timeout"] == 1


@pytest.mark.asyncio
async def test_medical_card_budget_timeout_during_resolution_has_no_pet_fallback(monkeypatch):
    async def slow(_self):
        await asyncio.sleep(1)
    monkeypatch.setattr(VetmanagerClient, "_resolve_host", slow)
    monkeypatch.setattr(vetmanager_client, "READ_REQUEST_BUDGET_SECONDS", 0.01)
    headers, runtime = patch_runtime_credentials("stage443budgettool", "mock-key", bearer_token="mock-token")
    with headers, runtime:
        with pytest.raises(ToolError) as error:
            await mcp.call_tool("get_medical_cards_by_date", {"date": "2026-10-20", "limit": 1})
    assert "sequentially try get_medical_cards" not in str(error.value)
