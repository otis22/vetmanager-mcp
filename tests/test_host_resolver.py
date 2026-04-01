"""Unit tests for host_resolver.py."""

import pytest
import respx
import httpx

from exceptions import HostResolutionError, VetmanagerError, VetmanagerTimeoutError
from host_resolver import resolve_vetmanager_host

DOMAIN = "testclinic"
BILLING_URL = f"https://billing-api.vetmanager.cloud/host/{DOMAIN}"
RESOLVED_HOST = "https://testclinic.vetmanager.cloud"


@pytest.mark.asyncio
@respx.mock
async def test_happy_path():
    respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": RESOLVED_HOST}})
    )
    result = await resolve_vetmanager_host(DOMAIN)
    assert result == RESOLVED_HOST


@pytest.mark.asyncio
@respx.mock
async def test_url_without_scheme_gets_https_prefix():
    respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": "testclinic.vetmanager.cloud"}})
    )
    result = await resolve_vetmanager_host(DOMAIN)
    assert result == RESOLVED_HOST


@pytest.mark.asyncio
@respx.mock
async def test_trailing_slash_stripped():
    respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {"url": f"{RESOLVED_HOST}/"}})
    )
    result = await resolve_vetmanager_host(DOMAIN)
    assert result == RESOLVED_HOST


@pytest.mark.asyncio
@respx.mock
async def test_retry_on_timeout():
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ReadTimeout("timeout")
        return httpx.Response(200, json={"data": {"url": RESOLVED_HOST}})

    respx.get(BILLING_URL).mock(side_effect=side_effect)
    result = await resolve_vetmanager_host(DOMAIN, max_retries=1)
    assert result == RESOLVED_HOST
    assert call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_all_retries_exhausted_raises_timeout():
    respx.get(BILLING_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(VetmanagerTimeoutError, match="Timeout"):
        await resolve_vetmanager_host(DOMAIN, max_retries=1)


@pytest.mark.asyncio
@respx.mock
async def test_no_retry_when_max_retries_zero():
    respx.get(BILLING_URL).mock(side_effect=httpx.ReadTimeout("timeout"))
    with pytest.raises(VetmanagerTimeoutError):
        await resolve_vetmanager_host(DOMAIN, max_retries=0)


@pytest.mark.asyncio
@respx.mock
async def test_http_error_raises_host_resolution_error():
    respx.get(BILLING_URL).mock(return_value=httpx.Response(404))
    with pytest.raises(HostResolutionError, match="404"):
        await resolve_vetmanager_host(DOMAIN)


@pytest.mark.asyncio
@respx.mock
async def test_empty_response_raises_host_resolution_error():
    respx.get(BILLING_URL).mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    with pytest.raises(HostResolutionError, match="Unexpected"):
        await resolve_vetmanager_host(DOMAIN)


@pytest.mark.asyncio
@respx.mock
async def test_network_error_with_retry():
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise httpx.ConnectError("connection refused")
        return httpx.Response(200, json={"data": {"url": RESOLVED_HOST}})

    respx.get(BILLING_URL).mock(side_effect=side_effect)
    result = await resolve_vetmanager_host(DOMAIN, max_retries=1)
    assert result == RESOLVED_HOST


@pytest.mark.asyncio
@respx.mock
async def test_network_error_all_retries_exhausted():
    respx.get(BILLING_URL).mock(side_effect=httpx.ConnectError("connection refused"))
    with pytest.raises(VetmanagerError, match="Network error"):
        await resolve_vetmanager_host(DOMAIN, max_retries=1)
