"""Unit tests: VetmanagerClient runtime auth, caching and transport security."""

import asyncio
import time
from unittest.mock import patch

import httpx
import pytest
import respx

import auth.request as auth_request
import vetmanager_client
from exceptions import AuthError, HostResolutionError, NotFoundError, VetmanagerError
from tests.runtime_factories import (
    make_client_with_resolved_runtime,
    patch_runtime_credentials,
)
from vetmanager_client import VetmanagerClient


def make_host_response(url: str) -> dict:
    return {"data": {"url": url}}


def make_client(domain: str, api_key: str) -> VetmanagerClient:
    return make_client_with_resolved_runtime(domain, api_key)


def make_bearer_client_without_resolved_credentials(_: str, __: str) -> VetmanagerClient:
    headers = {"authorization": "Bearer integration-token"}
    with patch.object(auth_request, "_get_request_headers", return_value=headers):
        return VetmanagerClient()


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
    respx.get("https://a.vetmanager.cloud/rest/api/client").mock(return_value=httpx.Response(200, json={"data": [{"id": 1}]}))
    respx.get("https://b.vetmanager.cloud/rest/api/client").mock(return_value=httpx.Response(200, json={"data": [{"id": 2}]}))

    ca = make_client("clinic-a", "key-a")
    cb = make_client("clinic-b", "key-b")

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
    respx.get("https://c.vetmanager.cloud/rest/api/client").mock(return_value=httpx.Response(200, json={"data": []}))

    vc = make_client("clinic-c", "key-c")
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
    respx.get("https://d.vetmanager.cloud/rest/api/user").mock(return_value=httpx.Response(200, json={"data": "d"}))
    respx.get("https://e.vetmanager.cloud/rest/api/user").mock(return_value=httpx.Response(200, json={"data": "e"}))

    cd = make_client("clinic-d", "key-d")
    ce = make_client("clinic-e", "key-e")

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
    respx.get("https://f.vetmanager.cloud/rest/api/client").mock(return_value=httpx.Response(401, json={"error": "unauthorized"}))

    vc = make_client("clinic-f", "bad-key")
    with pytest.raises(AuthError):
        await vc.get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_not_found_error_on_404():
    """Client must raise NotFoundError on HTTP 404."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-g").mock(
        return_value=httpx.Response(200, json=make_host_response("https://g.vetmanager.cloud"))
    )
    respx.get("https://g.vetmanager.cloud/rest/api/client/999").mock(return_value=httpx.Response(404, json={"error": "not found"}))

    vc = make_client("clinic-g", "key-g")
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

    vc = make_client("clinic-h", "my-secret-key")
    await vc.get("/rest/api/client")

    assert captured_request is not None
    assert captured_request.headers["X-REST-API-KEY"] == "my-secret-key"


def test_missing_headers_raise_error():
    """Runtime must reject requests without bearer credentials."""
    with patch.object(auth_request, "_get_request_headers", return_value={}):
        with pytest.raises(AuthError, match="Missing Authorization"):
            VetmanagerClient()


def test_bearer_header_initializes_client_for_lazy_runtime_resolution():
    """Client accepts bearer header and resolves concrete credentials lazily later."""
    fake_headers = {"authorization": "Bearer vm_st_token"}
    with patch.object(auth_request, "_get_request_headers", return_value=fake_headers):
        vc = VetmanagerClient()
    assert vc._auth_source is None
    assert vc._domain is None
    assert vc._api_key is None


@pytest.mark.asyncio
async def test_invalid_domain_rejected():
    """Invalid domain from bearer runtime context must be rejected before network access."""
    vc = make_bearer_client_without_resolved_credentials("bad.domain", "header-key")
    _, runtime_patch = patch_runtime_credentials("bad.domain", "header-key")
    with runtime_patch:
        with pytest.raises(VetmanagerError, match="Invalid Vetmanager domain"):
            await vc.get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_non_allowlisted_or_non_https_host_rejected():
    """Resolved host must be HTTPS and from allowlisted domains."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-z").mock(
        return_value=httpx.Response(200, json=make_host_response("http://evil.example"))
    )
    vc = make_client("clinic-z", "key-z")
    with pytest.raises(HostResolutionError):
        await vc.get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
@pytest.mark.security
async def test_resolved_host_rejects_userinfo_and_custom_port():
    """Billing host must be a bare HTTPS origin without userinfo or custom port."""
    route = respx.get("https://billing-api.vetmanager.cloud/host/clinic-unsafe")
    route.mock(
        return_value=httpx.Response(
            200,
            json=make_host_response("https://user:pass@clinic-unsafe.vetmanager.cloud:444"),
        )
    )
    vc = make_client("clinic-unsafe", "key-unsafe")

    with pytest.raises(HostResolutionError):
        await vc.get("/rest/api/client")


@pytest.mark.asyncio
@respx.mock
async def test_client_can_resolve_credentials_via_runtime_auth_context():
    """Client should use runtime_auth resolver for bearer-authenticated requests."""
    respx.get("https://billing-api.vetmanager.cloud/host/bearer-clinic").mock(
        return_value=httpx.Response(200, json=make_host_response("https://bearer.vetmanager.cloud"))
    )
    respx.get("https://bearer.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    vc = make_bearer_client_without_resolved_credentials("bearer-clinic", "bearer-key")
    _, runtime_patch = patch_runtime_credentials("bearer-clinic", "bearer-key")
    with runtime_patch:
        await vc.get("/rest/api/client")

    assert vc._auth_source == "bearer"
    assert vc._domain == "bearer-clinic"
    assert vc._api_key == "bearer-key"


@pytest.mark.asyncio
@respx.mock
async def test_wait_50ms_between_sequential_requests(monkeypatch):
    """Second sequential request must trigger `_pace_requests` sleep ≥ REQUEST_GAP_SECONDS.

    Stage 109.8: deterministic check via `asyncio.sleep` stub recording
    every invocation, instead of wall-clock elapsed >= 40ms — the old
    assertion was flaky on loaded CI where scheduler jitter pushed the
    second HTTP mock + pacing inside the same 35ms window.

    What we verify:
    - At least one sleep was invoked (the pacing lock fired).
    - The largest recorded sleep is ≥ REQUEST_GAP_SECONDS (50ms).
    Upstream respx mocks stay instant — the only sleep of meaningful
    size in the flow is `_pace_requests`.
    """
    import asyncio
    from vetmanager_client import REQUEST_GAP_SECONDS

    respx.get("https://billing-api.vetmanager.cloud/host/clinic-p").mock(
        return_value=httpx.Response(200, json=make_host_response("https://p.vetmanager.cloud"))
    )
    respx.get("https://p.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    sleeps: list[float] = []
    original_sleep = asyncio.sleep

    async def _recording_sleep(delay, *args, **kwargs):
        sleeps.append(float(delay))
        # Don't actually wait — tests run instantly.
        return await original_sleep(0)

    monkeypatch.setattr("vetmanager_client.asyncio.sleep", _recording_sleep)

    vc = make_client("clinic-p", "key-p")
    await vc.get("/rest/api/client", params={"limit": 1, "offset": 0})
    await vc.get("/rest/api/client", params={"limit": 2, "offset": 0})

    # At least one POSITIVE sleep is strong evidence of pacing firing.
    # Actual values depend on scheduling jitter: `_pace_requests` computes
    # `REQUEST_GAP_SECONDS - (now - last_request_started_at)`, so a slow
    # first call leaves a smaller remaining gap. Invariant: each paced
    # sleep is ≤ REQUEST_GAP_SECONDS, and the count of positive sleeps
    # equals the count of requests that had to wait (at least 1 for two
    # sequential requests).
    positive_sleeps = [s for s in sleeps if s > 0]
    assert positive_sleeps, (
        f"expected at least one positive sleep from _pace_requests, "
        f"recorded: {sleeps}"
    )
    assert all(s <= REQUEST_GAP_SECONDS + 0.001 for s in positive_sleeps), (
        f"paced sleep exceeded configured REQUEST_GAP_SECONDS={REQUEST_GAP_SECONDS}: "
        f"{positive_sleeps}"
    )


@pytest.mark.asyncio
@respx.mock
async def test_retry_on_timeout_then_success():
    """Client retries timeout errors and succeeds on the next attempt."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-r").mock(
        return_value=httpx.Response(200, json=make_host_response("https://r.vetmanager.cloud"))
    )
    route = respx.get("https://r.vetmanager.cloud/rest/api/client")
    route.side_effect = [httpx.TimeoutException("timeout"), httpx.Response(200, json={"data": []})]

    vc = make_client("clinic-r", "key-r")
    result = await vc.get("/rest/api/client")
    assert result["data"] == []
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_response_is_cached_by_key():
    """Second identical GET should be served from cache."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-cache").mock(
        return_value=httpx.Response(200, json=make_host_response("https://cache.vetmanager.cloud"))
    )
    route = respx.get("https://cache.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 77}]})
    )

    vc = make_client("clinic-cache", "cache-key")
    first = await vc.get("/rest/api/client", params={"limit": 5, "offset": 0})
    second = await vc.get("/rest/api/client", params={"limit": 5, "offset": 0})

    assert first == second
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_cache_is_shared_between_instances_with_same_api_key():
    """Cache key should allow reuse between instances in one process."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-shared").mock(
        return_value=httpx.Response(200, json=make_host_response("https://shared.vetmanager.cloud"))
    )
    route = respx.get("https://shared.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )

    c1 = make_client("clinic-shared", "same-key")
    c2 = make_client("clinic-shared", "same-key")

    await c1.get("/rest/api/user", params={"limit": 5, "offset": 0})
    await c2.get("/rest/api/user", params={"limit": 5, "offset": 0})

    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_cache_isolated_by_api_key_hash():
    """Different API keys must not share cache for the same URL."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-isolated").mock(
        return_value=httpx.Response(200, json=make_host_response("https://isolated.vetmanager.cloud"))
    )
    route = respx.get("https://isolated.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 2}]})
    )

    c1 = make_client("clinic-isolated", "key-one")
    c2 = make_client("clinic-isolated", "key-two")

    await c1.get("/rest/api/user", params={"limit": 5, "offset": 0})
    await c2.get("/rest/api/user", params={"limit": 5, "offset": 0})

    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_cache_shared_within_same_account_id():
    """Two instances with the same explicit account_id should share cache."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-acct").mock(
        return_value=httpx.Response(200, json=make_host_response("https://acct.vetmanager.cloud"))
    )
    route = respx.get("https://acct.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 9}]})
    )

    c1 = make_client_with_resolved_runtime(
        "clinic-acct", "shared-key", account_id=42, bearer_token_id=1, connection_id=1,
    )
    c2 = make_client_with_resolved_runtime(
        "clinic-acct", "shared-key", account_id=42, bearer_token_id=1, connection_id=1,
    )

    await c1.get("/rest/api/user", params={"limit": 5, "offset": 0})
    await c2.get("/rest/api/user", params={"limit": 5, "offset": 0})

    # Same account_id → same cache key → only one upstream call
    assert route.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_cache_account_id_none_does_not_collide_with_numeric():
    """Cache key with account_id=None must not collide with numeric account_id."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-none").mock(
        return_value=httpx.Response(200, json=make_host_response("https://none.vetmanager.cloud"))
    )
    route = respx.get("https://none.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 1}]})
    )

    c_none = make_client_with_resolved_runtime(
        "clinic-none", "k", account_id=1, bearer_token_id=1, connection_id=1,
    )
    c_none._account_id = None  # simulate legacy/uninitialized account context
    c_numeric = make_client_with_resolved_runtime(
        "clinic-none", "k", account_id=1, bearer_token_id=1, connection_id=1,
    )

    await c_none.get("/rest/api/user", params={"limit": 5, "offset": 0})
    await c_numeric.get("/rest/api/user", params={"limit": 5, "offset": 0})

    # Different cache keys (acct:none vs acct:1) → both call upstream
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_get_cache_isolated_by_account_id():
    """Two clients with identical credentials but different account_id must not share cache."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-shared").mock(
        return_value=httpx.Response(200, json=make_host_response("https://shared.vetmanager.cloud"))
    )
    route = respx.get("https://shared.vetmanager.cloud/rest/api/user").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 7}]})
    )

    # Both clients use the SAME domain and api_key but DIFFERENT account_id
    c_account1 = make_client_with_resolved_runtime(
        "clinic-shared", "shared-key", account_id=100, bearer_token_id=1, connection_id=1,
    )
    c_account2 = make_client_with_resolved_runtime(
        "clinic-shared", "shared-key", account_id=200, bearer_token_id=2, connection_id=2,
    )

    await c_account1.get("/rest/api/user", params={"limit": 5, "offset": 0})
    await c_account2.get("/rest/api/user", params={"limit": 5, "offset": 0})

    # Two distinct cache keys → upstream called twice
    assert route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_post_invalidates_domain_entity_tag_cache():
    """Mutation should invalidate cached GET for same domain/entity tag."""
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-invalidate").mock(
        return_value=httpx.Response(200, json=make_host_response("https://inv.vetmanager.cloud"))
    )
    get_route = respx.get("https://inv.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 9}]})
    )
    post_route = respx.post("https://inv.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(201, json={"data": {"id": 10}})
    )

    vc = make_client("clinic-invalidate", "inv-key")
    await vc.get("/rest/api/client", params={"limit": 5, "offset": 0})
    await vc.get("/rest/api/client", params={"limit": 5, "offset": 0})
    await vc.post("/rest/api/client", json={"firstName": "A", "lastName": "B"})
    await vc.get("/rest/api/client", params={"limit": 5, "offset": 0})

    assert post_route.call_count == 1
    assert get_route.call_count == 2


@pytest.mark.asyncio
@respx.mock
async def test_cache_entry_expires_after_ttl(monkeypatch: pytest.MonkeyPatch):
    """Cached GET should expire after configured TTL."""
    monkeypatch.setattr(vetmanager_client, "CACHE_TTL_SECONDS", 0.01)
    monkeypatch.setattr(vetmanager_client, "CACHE_TTL_SHORT_SECONDS", 0.01)
    respx.get("https://billing-api.vetmanager.cloud/host/clinic-ttl").mock(
        return_value=httpx.Response(200, json=make_host_response("https://ttl.vetmanager.cloud"))
    )
    route = respx.get("https://ttl.vetmanager.cloud/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": [{"id": 101}]})
    )

    vc = make_client("clinic-ttl", "ttl-key")
    await vc.get("/rest/api/client", params={"limit": 1, "offset": 0})
    await asyncio.sleep(0.02)
    await vc.get("/rest/api/client", params={"limit": 1, "offset": 0})

    assert route.call_count == 2
