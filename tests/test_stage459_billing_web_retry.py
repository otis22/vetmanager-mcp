"""Web connection validation uses the existing bounded billing retry."""

import httpx
import pytest
import respx

from exceptions import HostResolutionTimeoutError
from vetmanager_connection_service import resolve_vetmanager_host


@pytest.mark.asyncio
@respx.mock
async def test_web_resolution_retries_a_transient_cloud_timeout():
    domain = "stage459webretry"
    origin = f"https://{domain}.vetmanager2.ru"
    calls = 0

    def cloud(_request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ConnectTimeout("transient")
        return httpx.Response(200, json={"url": origin})

    primary = respx.get(f"https://billing-api.vetmanager.cloud/host/{domain}").mock(
        side_effect=cloud
    )
    alias = respx.get(f"https://billing-api.vetmanager.ru/host/{domain}").mock(
        return_value=httpx.Response(200, json={"url": origin})
    )

    assert await resolve_vetmanager_host(domain) == origin
    assert primary.call_count == 2
    assert alias.call_count == 0


@pytest.mark.asyncio
@respx.mock
async def test_web_resolution_persistent_timeouts_still_fail():
    domain = "stage459webfail"
    for base in (
        "https://billing-api.vetmanager.cloud/host/",
        "https://billing-api.vetmanager.ru/host/",
    ):
        respx.get(base + domain).mock(side_effect=httpx.ConnectTimeout("persistent"))
    for suffix in ("vetmanager2.ru", "vetmanager.ru"):
        respx.get(f"https://{domain}.{suffix}/rest/api/user/1").mock(
            side_effect=httpx.ConnectTimeout("persistent")
        )

    with pytest.raises(HostResolutionTimeoutError):
        await resolve_vetmanager_host(domain)
