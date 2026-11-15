"""Measured billing lookup budget without widening clinic probes."""

import asyncio

import httpx
import pytest

import host_resolver as resolver
from exceptions import HostResolutionTimeoutError


DOMAIN = "stage459-timeout"
ORIGIN = f"https://{DOMAIN}.vetmanager2.ru"


@pytest.mark.asyncio
async def test_billing_accepts_measured_slow_response(monkeypatch):
    class Client:
        async def get(self, url, **kwargs):
            assert kwargs == {"follow_redirects": False}
            await asyncio.sleep(2.7)
            return httpx.Response(200, json={"url": ORIGIN})

    monkeypatch.setattr(resolver, "_get_shared_client", lambda: asyncio.sleep(0, result=Client()))
    assert await resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN


@pytest.mark.asyncio
async def test_billing_still_times_out_and_retries_are_bounded(monkeypatch):
    calls = []

    class Client:
        async def get(self, url, **kwargs):
            calls.append(url)
            await asyncio.Event().wait()

    monkeypatch.setattr(resolver, "_get_shared_client", lambda: asyncio.sleep(0, result=Client()))
    monkeypatch.setattr(resolver, "_BILLING_LOOKUP_DEADLINE_SECONDS", 0.02, raising=False)
    monkeypatch.setattr(resolver, "_LOOKUP_DEADLINE_SECONDS", 0.02)
    with pytest.raises(HostResolutionTimeoutError):
        await resolver.resolve_vetmanager_host(DOMAIN, max_retries=1)
    assert len(calls) == 6  # two attempts per billing source, then two probes


def test_billing_and_probe_worst_case_fits_get_budget():
    assert resolver._BILLING_LOOKUP_DEADLINE_SECONDS > 5.506
    assert resolver._REQUEST_TIMEOUT.connect >= resolver._BILLING_LOOKUP_DEADLINE_SECONDS
    assert resolver._REQUEST_TIMEOUT.read >= resolver._BILLING_LOOKUP_DEADLINE_SECONDS
    assert (4 * resolver._BILLING_LOOKUP_DEADLINE_SECONDS
            + 2 * resolver._LOOKUP_DEADLINE_SECONDS + 0.2) < 30.0
