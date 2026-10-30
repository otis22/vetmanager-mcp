"""Hotfix: billing alias and bounded emergency origin fallback."""

import logging

import httpx
import certifi
import ssl
import pytest
import respx

import host_resolver
from exceptions import HostResolutionError
from service_metrics import snapshot_service_metrics

DOMAIN = "stage448"
CLOUD = f"https://billing-api.vetmanager.cloud/host/{DOMAIN}"
ALIAS = f"https://billing-api.vetmanager.ru/host/{DOMAIN}"
ORIGIN = f"https://{DOMAIN}.vetmanager2.ru"
RU_ORIGIN = f"https://{DOMAIN}.vetmanager.ru"
VM2_PROBE = f"{ORIGIN}/rest/api/user/1"
RU_PROBE = f"{RU_ORIGIN}/rest/api/user/1"


def _billing_transport_down():
    respx.get(CLOUD).mock(side_effect=httpx.ConnectTimeout("cloud"))
    respx.get(ALIAS).mock(side_effect=httpx.ConnectError("alias"))


@pytest.mark.asyncio
@respx.mock
async def test_primary_cloud_success_skips_alias(caplog):
    caplog.set_level(logging.DEBUG, logger=host_resolver.RUNTIME_LOGGER.name)
    cloud = respx.get(CLOUD).mock(return_value=httpx.Response(200, json={"url": ORIGIN}))
    alias = respx.get(ALIAS).mock(return_value=httpx.Response(200, json={"url": ORIGIN}))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert cloud.call_count == 1
    assert alias.call_count == 0
    assert any(record.event_name == "billing_host_resolved" and record.levelno == logging.DEBUG
               for record in caplog.records if hasattr(record, "event_name"))
    assert not any(getattr(record, "event_name", None) == "billing_host_resolved_via_fallback"
                   for record in caplog.records)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("failure", [httpx.ConnectTimeout("timeout"), httpx.Response(503)])
async def test_cloud_failure_uses_alias(failure):
    respx.get(CLOUD).mock(side_effect=failure if isinstance(failure, Exception) else None,
                          return_value=failure if isinstance(failure, httpx.Response) else None)
    alias = respx.get(ALIAS).mock(return_value=httpx.Response(200, json={"url": ORIGIN}))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert alias.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_cloud_5xx_logs_source_and_reason(caplog):
    respx.get(CLOUD).mock(return_value=httpx.Response(503))
    respx.get(ALIAS).mock(return_value=httpx.Response(200, json={"url": ORIGIN}))
    assert await host_resolver.resolve_vetmanager_host(
        DOMAIN, max_retries=0, correlation_id="corr-448"
    ) == ORIGIN
    assert any(
        getattr(record, "event_name", None) == "billing_api_http_failure"
        and record.levelno == logging.WARNING
        and record.source == "cloud"
        and record.domain == DOMAIN
        and record.reason == "http_5xx"
        and record.status_code == 503
        and record.correlation_id == "corr-448"
        for record in caplog.records
    )


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(("failure", "expected_reason"), [
    (httpx.ConnectTimeout("cloud"), "connect_timeout"),
    (httpx.ReadTimeout("cloud"), "read_timeout"),
    (httpx.Response(503), "http_5xx"),
])
async def test_alias_success_logs_fallback_and_primary_reason(caplog, failure, expected_reason):
    respx.get(CLOUD).mock(side_effect=failure if isinstance(failure, Exception) else None,
                          return_value=failure if isinstance(failure, httpx.Response) else None)
    respx.get(ALIAS).mock(return_value=httpx.Response(200, json={"url": ORIGIN}))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert any(
        getattr(record, "event_name", None) == "billing_host_resolved_via_fallback"
        and record.levelno == logging.WARNING
        and record.source == "alias"
        and record.domain == DOMAIN
        and record.primary_failure_reason == expected_reason
        and record.resolved_host == ORIGIN
        for record in caplog.records
    )


@pytest.mark.asyncio
@respx.mock
async def test_both_transport_failures_use_short_cached_guess(caplog, monkeypatch):
    clock = [100.0]
    monkeypatch.setattr(host_resolver.time, "monotonic", lambda: clock[0])
    cloud = respx.get(CLOUD).mock(side_effect=httpx.ConnectTimeout("cloud"))
    alias = respx.get(ALIAS).mock(side_effect=httpx.ConnectError("alias"))
    probe = respx.get(VM2_PROBE).mock(return_value=httpx.Response(401))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert cloud.call_count == alias.call_count == 1
    clock[0] += host_resolver.GUESSED_HOST_CACHE_TTL_SECONDS + 1
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert cloud.call_count == alias.call_count == 2
    assert probe.call_count == 2
    assert host_resolver.GUESSED_HOST_CACHE_TTL_SECONDS < host_resolver.BILLING_RESOLVER_CACHE_TTL_SECONDS
    assert any(getattr(record, "event_name", None) == "billing_host_guessed" for record in caplog.records)
    assert any(getattr(record, "event_name", None) == "billing_api_transport_failure"
               and record.reason == "connect_timeout" and record.levelno == logging.WARNING
               for record in caplog.records)
    assert snapshot_service_metrics()["upstream_requests_total"]["billing_api|guessed_vm2_direct"] == 3


@pytest.mark.asyncio
@respx.mock
async def test_vm2_probe_has_no_clinic_key_and_no_redirect_follow():
    _billing_transport_down()
    vm2 = respx.get(VM2_PROBE).mock(return_value=httpx.Response(200, json={"data": []}))
    ru = respx.get(RU_PROBE).mock(return_value=httpx.Response(401))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert "X-REST-API-KEY" not in vm2.calls[0].request.headers
    assert ru.call_count == 0


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("vm2_response", [
    httpx.Response(302, headers={"Location": "https://vetmanager.ru/404"}),
    httpx.Response(404),
])
async def test_vm2_redirect_or_404_tries_ru_direct(vm2_response):
    _billing_transport_down()
    respx.get(VM2_PROBE).mock(return_value=vm2_response)
    ru = respx.get(RU_PROBE).mock(return_value=httpx.Response(401))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == RU_ORIGIN
    assert ru.call_count == 1
    assert snapshot_service_metrics()["upstream_requests_total"]["billing_api|guessed_ru_direct"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_ru_redirect_to_same_clinic_vm2_is_accepted():
    _billing_transport_down()
    respx.get(VM2_PROBE).mock(return_value=httpx.Response(404))
    respx.get(RU_PROBE).mock(return_value=httpx.Response(302, headers={"Location": VM2_PROBE}))
    assert await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0) == ORIGIN
    assert snapshot_service_metrics()["upstream_requests_total"]["billing_api|guessed_ru_redirect"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_both_probes_redirect_to_404_is_not_found():
    _billing_transport_down()
    not_found = httpx.Response(302, headers={"Location": "https://vetmanager.ru/404"})
    respx.get(VM2_PROBE).mock(return_value=not_found)
    respx.get(RU_PROBE).mock(return_value=not_found)
    with pytest.raises(HostResolutionError, match="not found"):
        await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("location", [
    "https://evil.example/rest/api/user/1",
    "https://otherclinic.vetmanager2.ru/rest/api/user/1",
    "https://stage448.vetmanager2.ru:bad/rest/api/user/1",
    "/404",
    "",
])
async def test_ru_redirect_to_foreign_or_other_clinic_is_rejected(location):
    _billing_transport_down()
    respx.get(VM2_PROBE).mock(return_value=httpx.Response(404))
    respx.get(RU_PROBE).mock(return_value=httpx.Response(302, headers={"Location": location}))
    with pytest.raises(HostResolutionError):
        await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("response", [httpx.Response(404), httpx.Response(200, json={"success": False, "url": ORIGIN})])
async def test_authoritative_negative_never_guesses(response):
    respx.get(CLOUD).mock(side_effect=httpx.ConnectTimeout("cloud"))
    respx.get(ALIAS).mock(return_value=response)
    with pytest.raises(HostResolutionError):
        await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0)


@pytest.mark.asyncio
@respx.mock
async def test_cloud_5xx_and_alias_transport_does_not_guess():
    respx.get(CLOUD).mock(return_value=httpx.Response(503))
    respx.get(ALIAS).mock(side_effect=httpx.ConnectTimeout("alias"))
    with pytest.raises(Exception):
        await host_resolver.resolve_vetmanager_host(DOMAIN, max_retries=0)
    assert not any(
        key.startswith("billing_api|guessed_")
        for key in snapshot_service_metrics()["upstream_requests_total"]
    )


@pytest.mark.asyncio
async def test_billing_client_uses_classic_key_share(monkeypatch):
    captured = {}
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)

    class TLS:
        def set_ecdh_curve(self, curve):
            captured["curve"] = curve

    tls = TLS()
    def fake_context(**kwargs):
        captured.update(kwargs)
        return tls

    monkeypatch.setattr(ssl, "create_default_context", fake_context)

    class Client:
        is_closed = False

        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(host_resolver.httpx, "AsyncClient", Client)
    await host_resolver._get_shared_client()
    assert captured["verify"] is tls
    assert captured["curve"] == "prime256v1"
    assert captured["cafile"] == certifi.where()
    assert captured["timeout"].connect <= 3
