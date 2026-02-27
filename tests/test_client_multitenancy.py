"""Unit tests: VetmanagerClient multi-tenancy and independence."""

import pytest
import respx
import httpx

from vetmanager_client import VetmanagerClient
from exceptions import AuthError, NotFoundError, VetmanagerTimeoutError


def make_host_response(url: str) -> dict:
    return {"data": {"url": url}}


@pytest.mark.asyncio
@respx.mock
async def test_two_clients_resolve_different_hosts():
    """Two clients with different domains must resolve to different base URLs."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-a").mock(
        return_value=httpx.Response(200, json=make_host_response("https://a.vetmanager.cloud"))
    )
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-b").mock(
        return_value=httpx.Response(200, json=make_host_response("https://b.vetmanager.cloud"))
    )
    respx.get("https://a.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )
    respx.get("https://b.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 2}]})
    )

    ca = VetmanagerClient("clinic-a", "key-a")
    cb = VetmanagerClient("clinic-b", "key-b")

    result_a = await ca.get("/rest/api/client")
    result_b = await cb.get("/rest/api/client")

    assert result_a["data"][0]["id"] == 1
    assert result_b["data"][0]["id"] == 2


@pytest.mark.asyncio
@respx.mock
async def test_host_cached_within_same_instance():
    """Billing API must be called only once per client instance."""
    billing = respx.get("https://billing-api.vetmanager.cloud/host/clinic-c").mock(
        return_value=httpx.Response(200, json=make_host_response("https://c.vetmanager.cloud"))
    )
    respx.get("https://c.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    vc = VetmanagerClient("clinic-c", "key-c")
    await vc.get("/rest/api/client")
    await vc.get("/rest/api/client")

    assert billing.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_clients_do_not_share_cached_url():
    """Different instances of VetmanagerClient must NOT share cached URLs."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-d").mock(
        return_value=httpx.Response(200, json=make_host_response("https://d.vetmanager.cloud"))
    )
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-e").mock(
        return_value=httpx.Response(200, json=make_host_response("https://e.vetmanager.cloud"))
    )
    respx.get("https://d.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": "d"})
    )
    respx.get("https://e.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": "e"})
    )

    cd = VetmanagerClient("clinic-d", "key-d")
    ce = VetmanagerClient("clinic-e", "key-e")

    result_d = await cd.get("/rest/api/user")
    result_e = await ce.get("/rest/api/user")

    assert result_d["data"] == "d"
    assert result_e["data"] == "e"
    assert cd._base_url != ce._base_url


@pytest.mark.asyncio
@respx.mock
async def test_auth_error_on_401():
    """Client must raise AuthError on HTTP 401."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-f").mock(
        return_value=httpx.Response(200, json=make_host_response("https://f.vetmanager.cloud"))
    )
    respx.get("https://f.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(401, json={"error": "unauthorized"})
    )

    vc = VetmanagerClient("clinic-f", "bad-key")
    with pytest.raises(AuthError):
        await vc.get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_not_found_error_on_404():
    """Client must raise NotFoundError on HTTP 404."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-g").mock(
        return_value=httpx.Response(200, json=make_host_response("https://g.vetmanager.cloud"))
    )
    respx.get("https://g.vetmanager.cloud/rest/api/client/999").mock(
        return_value=httpx.Response(404, json={"error": "not found"})
    )

    vc = VetmanagerClient("clinic-g", "key-g")
    with pytest.raises(NotFoundError):
        await vc.get("/rest/api/client/999")


@pytest.mark.asyncio
@respx.mock
async def test_api_key_sent_in_header():
    """Client must pass X-REST-API-KEY header on every request."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-h").mock(
        return_value=httpx.Response(200, json=make_host_response("https://h.vetmanager.cloud"))
    )

    captured_request = None

    def capture(req: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = req
        return httpx.Response(200, json={"data": []})

    respx.get("https://h.vetmanager.cloud/rest/api/client").mock(side_effect=capture)

    vc = VetmanagerClient("clinic-h", "my-secret-key")
    await vc.get("/rest/api/client")

    assert captured_request is not None
    assert captured_request.headers["X-REST-API-KEY"] == "my-secret-key"
