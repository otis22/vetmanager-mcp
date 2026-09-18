"""Stage 327 regression guards for message metrics and clinic-local dates."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError
from zoneinfo import ZoneInfo

import clinic_timezone
from runtime_auth import use_runtime_credentials
from server import mcp
from service_metrics import reset_service_metrics, snapshot_service_metrics
from tests.runtime_factories import make_runtime_credentials, patch_runtime_credentials


DOMAIN = "stage327"
API_KEY = "stage327-key"
BASE = f"https://{DOMAIN}.vetmanager.cloud"


def _runtime(*, account_id: int, connection_id: int):
    return make_runtime_credentials(
        DOMAIN, API_KEY, account_id=account_id, connection_id=connection_id
    )


@pytest.mark.asyncio
async def test_two_clinics_at_midnight_have_different_today_and_share_bounded_cache(monkeypatch):
    clinic_timezone.reset_clinic_timezone_cache()
    zones = {1: "Pacific/Auckland", 2: "America/Los_Angeles"}
    calls: list[str] = []

    class Client:
        async def get(self, path):
            calls.append(path)
            clinic_id = int(path.rsplit("/", 1)[1])
            return {"data": {"clinics": {"time_zone": zones[clinic_id]}}}

    monkeypatch.setattr(clinic_timezone, "VetmanagerClient", Client)
    instant = datetime(2026, 1, 1, 1, tzinfo=timezone.utc)
    assert (await clinic_timezone.clinic_local_today(1, relative=True, now=instant)).isoformat() == "2026-01-01"
    assert (await clinic_timezone.clinic_local_today(2, relative=True, now=instant)).isoformat() == "2025-12-31"
    await clinic_timezone.clinic_local_today(1, relative=True, now=instant)
    assert calls == ["/rest/api/clinics/1", "/rest/api/clinics/2"]


@pytest.mark.asyncio
async def test_absolute_date_does_not_resolve_clinic_timezone(monkeypatch):
    async def unexpected(*args, **kwargs):
        raise AssertionError("absolute dates must not resolve clinic timezone")

    monkeypatch.setattr(clinic_timezone, "resolve_clinic_timezone", unexpected)
    await clinic_timezone.clinic_local_today(7, relative=False)


@pytest.mark.asyncio
async def test_null_invalid_and_transport_timezone_failures_have_scoped_ttls(monkeypatch):
    clinic_timezone.reset_clinic_timezone_cache()
    clock = [1000.0]
    calls: list[int] = []
    warnings: list[str] = []

    monkeypatch.setattr(
        clinic_timezone.RUNTIME_LOGGER,
        "warning",
        lambda event, **kwargs: warnings.append(event),
    )

    class Client:
        async def get(self, path):
            clinic_id = int(path.rsplit("/", 1)[1])
            calls.append(clinic_id)
            if clinic_id == 1:
                return {"data": {"clinics": {"time_zone": None}}}
            if clinic_id == 2:
                return {"data": {"clinics": {"time_zone": "../../etc/passwd"}}}
            raise httpx.ConnectError("offline")

    monkeypatch.setattr(clinic_timezone, "VetmanagerClient", Client)
    monotonic = lambda: clock[0]
    with use_runtime_credentials(_runtime(account_id=10, connection_id=20)):
        assert await clinic_timezone.resolve_clinic_timezone(1, monotonic=monotonic) is None
        assert await clinic_timezone.resolve_clinic_timezone(1, monotonic=monotonic) is None
        assert await clinic_timezone.resolve_clinic_timezone(2, monotonic=monotonic) is None
        assert await clinic_timezone.resolve_clinic_timezone(2, monotonic=monotonic) is None
        assert await clinic_timezone.resolve_clinic_timezone(3, monotonic=monotonic) is None
        assert await clinic_timezone.resolve_clinic_timezone(3, monotonic=monotonic) is None
        clock[0] += clinic_timezone.CLINIC_TIMEZONE_FAILURE_TTL_SECONDS + 1
        assert await clinic_timezone.resolve_clinic_timezone(3, monotonic=monotonic) is None
    assert calls == [1, 2, 3, 3]
    assert warnings == [
        "clinic_timezone_unavailable",
        "clinic_timezone_invalid",
        "clinic_timezone_unavailable",
        "clinic_timezone_unavailable",
    ]


@pytest.mark.asyncio
async def test_timezone_cache_is_scoped_to_tenant(monkeypatch):
    clinic_timezone.reset_clinic_timezone_cache()
    zones = iter(["Pacific/Auckland", "America/Los_Angeles"])

    class Client:
        async def get(self, path):
            return {"data": {"clinics": {"time_zone": next(zones)}}}

    monkeypatch.setattr(clinic_timezone, "VetmanagerClient", Client)
    with use_runtime_credentials(_runtime(account_id=1, connection_id=1)):
        first = await clinic_timezone.resolve_clinic_timezone(9)
    with use_runtime_credentials(_runtime(account_id=2, connection_id=2)):
        second = await clinic_timezone.resolve_clinic_timezone(9)
    assert first is not None and first.key == "Pacific/Auckland"
    assert second is not None and second.key == "America/Los_Angeles"


def test_tzdb_is_available_in_test_image():
    assert ZoneInfo("UTC").key == "UTC"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "endpoint", "arguments"),
    [
        ("send_message_to_all", "/rest/api/messages/all", {"message": "m", "campaign": "c"}),
        ("send_message_to_users", "/rest/api/messages/users", {"message": "m", "campaign": "c", "user_ids": [1]}),
        ("send_message_to_roles", "/rest/api/messages/roles", {"message": "m", "campaign": "c", "roles": ["doctor"]}),
    ],
)
@respx.mock
async def test_message_tools_emit_exact_success_and_error_metric_series(tool_name, endpoint, arguments):
    """Break by removing instrument_call from any send_message_* implementation."""
    reset_service_metrics()
    respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    respx.post(f"{BASE}{endpoint}").mock(
        side_effect=[
            httpx.Response(200, json={"success": True, "data": {}}),
            httpx.Response(500, json={"success": False}),
        ]
    )
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        result = await mcp.call_tool(tool_name, arguments)
        assert result.structured_content["success"] is True
        with pytest.raises(ToolError):
            await mcp.call_tool(tool_name, arguments)

    metrics = snapshot_service_metrics()
    metric_endpoint = f"{endpoint}:{tool_name}"
    assert metrics["tool_calls_total"][f"{metric_endpoint}|POST|success"] == 1
    assert metrics["tool_calls_total"][f"{metric_endpoint}|POST|error"] == 1
    latency = metrics["tool_call_latency_seconds"][f"{metric_endpoint}|POST"]
    assert latency["count"] == 2
