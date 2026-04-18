"""Stage 88 — observability core: correlation_id + per-tool + upstream metrics.

Covers:
- record_upstream_request records count + latency for success AND failure
- record_tool_call records count + latency for success AND error outcomes
- VetmanagerClient propagates X-Correlation-ID in outgoing headers
- Timeout / network error produce structured warning logs
- Prometheus output exposes the new metrics
- crud_helpers are instrumented
"""

import logging
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from service_metrics import (
    record_tool_call,
    record_upstream_request,
    render_prometheus_metrics,
    reset_service_metrics,
    snapshot_service_metrics,
)
from tests.runtime_factories import patch_runtime_credentials
from tools.crud_helpers import crud_list, crud_create
from vetmanager_client import VetmanagerClient

DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


# ── record_upstream_request ─────────────────────────────────────────────────


def test_record_upstream_request_accumulates_count_and_latency():
    reset_service_metrics()
    record_upstream_request(
        target="vetmanager_api", status="http_200", duration_seconds=0.12
    )
    record_upstream_request(
        target="vetmanager_api", status="http_200", duration_seconds=0.25
    )
    record_upstream_request(
        target="vetmanager_api", status="http_500", duration_seconds=0.05
    )

    snap = snapshot_service_metrics()
    assert snap["upstream_requests_total"]["vetmanager_api|http_200"] == 2
    assert snap["upstream_requests_total"]["vetmanager_api|http_500"] == 1

    latency_200 = snap["upstream_request_latency_seconds"]["vetmanager_api|http_200"]
    assert latency_200["count"] == 2
    assert latency_200["sum_seconds"] == pytest.approx(0.37, rel=1e-6)
    assert latency_200["max_seconds"] == pytest.approx(0.25, rel=1e-6)


# ── record_tool_call ────────────────────────────────────────────────────────


def test_record_tool_call_tracks_success_and_error_outcomes():
    reset_service_metrics()
    record_tool_call(
        endpoint="/rest/api/client", method="GET", outcome="success",
        duration_seconds=0.1,
    )
    record_tool_call(
        endpoint="/rest/api/client", method="GET", outcome="error",
        duration_seconds=0.03,
    )
    record_tool_call(
        endpoint="/rest/api/admission", method="POST", outcome="success",
        duration_seconds=0.5,
    )

    snap = snapshot_service_metrics()
    assert snap["tool_calls_total"]["/rest/api/client|GET|success"] == 1
    assert snap["tool_calls_total"]["/rest/api/client|GET|error"] == 1
    assert snap["tool_calls_total"]["/rest/api/admission|POST|success"] == 1


# ── correlation id propagation to VM API ────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_vm_api_request_includes_correlation_id_header():
    """Every outgoing VM API request MUST carry X-Correlation-ID so upstream
    logs can be joined with incoming MCP request logs."""
    reset_service_metrics()
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/client/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await VetmanagerClient().get("/rest/api/client/1")

    outgoing = route.calls.last.request.headers
    corr_id = outgoing.get("x-correlation-id")
    assert corr_id, f"expected X-Correlation-ID header, headers: {dict(outgoing)}"
    # When no context is available (test runs outside HTTP), a fresh UUID4 hex
    # is generated — 32 hex chars.
    assert len(corr_id) >= 8


# ── upstream latency metric recorded on success ─────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_upstream_request_metric_recorded_on_success():
    reset_service_metrics()
    billing_mock()
    respx.get(f"{BASE}/rest/api/client/1").mock(
        return_value=httpx.Response(200, json={"data": {"id": 1}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await VetmanagerClient().get("/rest/api/client/1")

    snap = snapshot_service_metrics()
    keys = [k for k in snap["upstream_requests_total"] if k.startswith("vetmanager_api|http_200")]
    assert keys, f"expected http_200 upstream counter, got {snap['upstream_requests_total']}"
    assert snap["upstream_requests_total"][keys[0]] == 1


# ── structured log + latency on timeout ─────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_timeout_emits_structured_warning_and_records_latency():
    """Verify timeout path: structured warning is emitted AND latency metric
    is recorded with status='timeout'.

    Stage 101.8: the old `_StubLogger` workaround — patching RUNTIME_LOGGER
    directly — was necessary because `configure_logging()` called
    `basicConfig(force=True)` at server.py import, wiping pytest's caplog
    handler. That root cause is fixed (configure_logging no longer resets
    root handlers). This test now uses a dedicated handler attached
    directly to the `vetmanager.runtime` logger, which is resilient to
    cross-test fixture interactions regardless of caplog state.
    """
    runtime_logger = logging.getLogger("vetmanager.runtime")
    collected: list[logging.LogRecord] = []

    class _ListHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            collected.append(record)

    handler = _ListHandler(level=logging.DEBUG)
    runtime_logger.addHandler(handler)
    # Stage 101.8: alembic test earlier in the suite calls
    # logging.config.fileConfig which defaults to
    # `disable_existing_loggers=True`, flipping `vetmanager.runtime.disabled`
    # to True. Revive it defensively (alembic/env.py now passes
    # `disable_existing_loggers=False`, but keep this re-enable as belt-and-
    # suspenders for any other dictConfig caller).
    prev_disabled = runtime_logger.disabled
    runtime_logger.disabled = False
    try:
        reset_service_metrics()
        billing_mock()
        respx.get(f"{BASE}/rest/api/client").mock(
            side_effect=httpx.TimeoutException("boom")
        )
        from exceptions import VetmanagerTimeoutError
        headers_patch, runtime_patch = bearer_runtime_patch()
        with headers_patch, runtime_patch:
            with pytest.raises(VetmanagerTimeoutError):
                await VetmanagerClient().get(
                    "/rest/api/client", params={"limit": 1}
                )
    finally:
        runtime_logger.removeHandler(handler)
        runtime_logger.disabled = prev_disabled

    timeout_records = [
        r for r in collected
        if getattr(r, "event_name", None) == "vm_upstream_timeout"
    ]
    assert timeout_records, (
        f"expected structured warning vm_upstream_timeout, "
        f"got {[r.getMessage() for r in collected]}"
    )
    record = timeout_records[0]
    assert record.domain == DOMAIN
    assert record.method == "GET"
    assert record.url_path == "/rest/api/client"
    assert isinstance(record.elapsed_ms, (int, float))

    snap = snapshot_service_metrics()
    assert snap["upstream_requests_total"].get("vetmanager_api|timeout") == 1


# ── per-tool metric via crud_helpers ────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_crud_list_instrumented_with_tool_metric_on_success():
    reset_service_metrics()
    billing_mock()
    respx.get(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(200, json={"data": {"client": [], "totalCount": 0}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await crud_list("/rest/api/client", limit=20, offset=0)

    snap = snapshot_service_metrics()
    # Stage 98.7: _instrumented_call composes endpoint#operation label so
    # list vs get_by_id vs create can be told apart on the same REST path.
    assert snap["tool_calls_total"].get("/rest/api/client#list|GET|success") == 1
    latency = snap["tool_call_latency_seconds"].get("/rest/api/client#list|GET")
    assert latency and latency["count"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_crud_create_instrumented_with_error_outcome_on_failure():
    reset_service_metrics()
    billing_mock()
    respx.post(f"{BASE}/rest/api/client").mock(
        return_value=httpx.Response(500, json={"error": "boom"})
    )
    from exceptions import VetmanagerError
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(VetmanagerError):
            await crud_create("/rest/api/client", {"firstName": "X"})

    snap = snapshot_service_metrics()
    assert snap["tool_calls_total"].get("/rest/api/client#create|POST|error") == 1


# ── Prometheus exposition ───────────────────────────────────────────────────


def test_prometheus_output_exposes_new_metrics():
    reset_service_metrics()
    record_upstream_request(
        target="vetmanager_api", status="http_200", duration_seconds=0.1
    )
    record_tool_call(
        endpoint="/rest/api/pet", method="GET", outcome="success",
        duration_seconds=0.05,
    )
    text = render_prometheus_metrics()

    assert "vetmanager_upstream_requests_total" in text
    assert "vetmanager_upstream_request_latency_seconds" in text
    assert "vetmanager_tool_calls_total" in text
    assert "vetmanager_tool_call_latency_seconds" in text
    # And the concrete labeled rows are present
    assert 'target="vetmanager_api"' in text
    assert 'endpoint="/rest/api/pet"' in text
