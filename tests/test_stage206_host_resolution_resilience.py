"""Stage 206 transport taxonomy and privacy regressions."""

import httpx
import pytest
import respx

from host_resolver import resolve_vetmanager_host
from service_metrics import snapshot_service_metrics
from upstream_transport import classify_http_status, classify_transport_error


DOMAIN = "stage206clinic"
BILLING_URL = f"https://billing-api.vetmanager.cloud/host/{DOMAIN}"


@pytest.mark.parametrize(
    ("exc", "reason"),
    [
        (httpx.ConnectTimeout("timeout"), "connect_timeout"),
        (httpx.ReadTimeout("timeout"), "read_timeout"),
        (httpx.WriteTimeout("timeout"), "timeout"),
        (httpx.ConnectError("dns or connection"), "connect_error"),
        (httpx.NetworkError("network"), "network_error"),
    ],
)
def test_transport_error_reasons_are_typed_and_bounded(exc, reason):
    assert classify_transport_error(exc) == reason


def test_http_status_reasons_are_bounded_by_class():
    assert classify_http_status(404) == "http_4xx"
    assert classify_http_status(503) == "http_5xx"


@pytest.mark.asyncio
@respx.mock
async def test_billing_read_timeout_has_safe_message_metric_and_correlation(caplog):
    respx.get(BILLING_URL).mock(side_effect=httpx.ReadTimeout("secret upstream detail"))

    with pytest.raises(Exception, match="Timeout resolving Vetmanager host"):
        await resolve_vetmanager_host(DOMAIN, max_retries=0, correlation_id="corr-206")

    metrics = snapshot_service_metrics()
    assert metrics["upstream_failures_total"]["billing_api|read_timeout"] == 1
    record = next(record for record in caplog.records if record.event_name == "billing_api_transport_failure")
    assert record.correlation_id == "corr-206"
    assert "secret upstream detail" not in record.getMessage()


@pytest.mark.asyncio
@respx.mock
async def test_billing_invalid_payload_is_not_recorded_as_success():
    respx.get(BILLING_URL).mock(return_value=httpx.Response(200, json={"data": {}}))

    with pytest.raises(Exception, match="Unexpected billing API host response"):
        await resolve_vetmanager_host(DOMAIN, max_retries=0)

    metrics = snapshot_service_metrics()
    assert metrics["upstream_failures_total"]["billing_api|malformed_response"] == 1
    assert "billing_api|http_200" not in metrics["upstream_requests_total"]


@pytest.mark.asyncio
@respx.mock
async def test_billing_non_json_payload_is_recorded_as_malformed_response():
    respx.get(BILLING_URL).mock(return_value=httpx.Response(200, text="not-json"))

    with pytest.raises(Exception, match="Unexpected billing API host response"):
        await resolve_vetmanager_host(DOMAIN, max_retries=0)

    metrics = snapshot_service_metrics()
    assert metrics["upstream_failures_total"]["billing_api|malformed_response"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_billing_null_nested_data_is_recorded_as_malformed_response():
    respx.get(BILLING_URL).mock(return_value=httpx.Response(200, json={"data": None}))

    with pytest.raises(Exception, match="Unexpected billing API host response"):
        await resolve_vetmanager_host(DOMAIN, max_retries=0)

    metrics = snapshot_service_metrics()
    assert metrics["upstream_failures_total"]["billing_api|malformed_response"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_billing_invalid_origin_does_not_expose_response_host():
    raw_host = "https://untrusted.example.test"
    respx.get(BILLING_URL).mock(return_value=httpx.Response(200, json={"url": raw_host}))

    with pytest.raises(Exception, match="Billing API returned an invalid host response") as error:
        await resolve_vetmanager_host(DOMAIN, max_retries=0)

    assert raw_host not in str(error.value)
    metrics = snapshot_service_metrics()
    assert metrics["upstream_failures_total"]["billing_api|invalid_origin"] == 1
