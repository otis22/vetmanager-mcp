"""Stage 398: dated medical-card read timeout guidance and bounded metrics."""

import asyncio
from datetime import date
from threading import Event

import pytest
from fastmcp.exceptions import ToolError

from exceptions import VetmanagerError, VetmanagerTimeoutError
from server import mcp
from service_metrics import snapshot_service_metrics
import shared_metric_counters
import tools.medical_card as medical_card_module
from tests.runtime_factories import patch_runtime_credentials
from vetmanager_client import VetmanagerClient


ARGS = {"date_from": "2026-07-01", "date_to": "2026-07-03", "limit": 1, "offset": 1}
LABEL = "/rest/api/MedicalCards#list:get_medical_cards_by_date|GET"


def _runtime():
    return patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock-token")


@pytest.mark.asyncio
async def test_dated_cards_success_records_own_tool_series(monkeypatch):
    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [], "totalCount": 0}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime:
        result = await mcp.call_tool("get_medical_cards_by_date", ARGS)
    assert result.structured_content["medical_cards_count"] == 0
    metrics = snapshot_service_metrics()
    assert metrics["tool_calls_total"][f"{LABEL}|success"] == 1
    assert metrics["tool_call_latency_seconds"][LABEL]["count"] == 1


@pytest.mark.asyncio
async def test_dated_cards_timeout_names_complete_safe_recovery(monkeypatch):
    async def get(_self, _path, **_kwargs):
        raise VetmanagerTimeoutError("Vetmanager request time budget was exhausted. Please retry shortly.")

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError) as failure:
        await mcp.call_tool("get_medical_cards_by_date", ARGS)
    message = str(failure.value)
    for required in ("each day", "offset=0", "all pages", "medical-card ID", "incomplete"):
        assert required in message
    assert "doctor_id" in message and "attending" in message
    assert "creator_id" in message and "author" in message
    assert "clinic_id" in message and "branch" in message
    assert "only if" in message
    assert "get_medical_cards" in message and "date_create" in message
    assert "known pet_id" in message and "incomplete" in message
    assert "testclinic" not in message and "test-key-mock" not in message
    assert snapshot_service_metrics()["tool_calls_total"][f"{LABEL}|timeout"] == 1


@pytest.mark.asyncio
async def test_dated_cards_other_upstream_error_keeps_error_outcome(monkeypatch):
    async def get(_self, _path, **_kwargs):
        raise VetmanagerError("Temporary upstream failure", status_code=500)

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError) as failure:
        await mcp.call_tool("get_medical_cards_by_date", ARGS)
    assert "each day" not in str(failure.value)
    assert snapshot_service_metrics()["tool_calls_total"][f"{LABEL}|error"] == 1


@pytest.mark.asyncio
async def test_dated_cards_invalid_response_counts_as_error(monkeypatch):
    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [], "totalCount": "invalid"}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError):
        await mcp.call_tool("get_medical_cards_by_date", ARGS)
    assert snapshot_service_metrics()["tool_calls_total"][f"{LABEL}|error"] == 1


@pytest.mark.asyncio
async def test_dated_cards_false_success_payload_counts_as_error(monkeypatch):
    async def get(_self, _path, **_kwargs):
        return {"success": False, "data": {"medicalCards": [], "totalCount": 0}}

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime:
        result = await mcp.call_tool("get_medical_cards_by_date", ARGS)
    assert result.structured_content["success"] is False
    assert snapshot_service_metrics()["tool_calls_total"][f"{LABEL}|error"] == 1


@pytest.mark.asyncio
async def test_dated_cards_latency_includes_relative_date_resolution(monkeypatch):
    async def slow_clinic_today(_clinic_id, *, relative):
        assert relative is True
        await asyncio.sleep(0.1)
        return date(2026, 7, 1)

    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [], "totalCount": 0}}

    monkeypatch.setattr(medical_card_module, "clinic_local_today", slow_clinic_today)
    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime:
        await mcp.call_tool("get_medical_cards_by_date", {"date": "today", "clinic_id": 1})
    latency = snapshot_service_metrics()["tool_call_latency_seconds"][LABEL]
    assert latency["sum_seconds"] >= 0.09


@pytest.mark.asyncio
async def test_dated_cards_invalid_range_records_error_before_upstream(monkeypatch):
    async def get(_self, _path, **_kwargs):
        raise AssertionError("upstream must not be called")

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError):
        await mcp.call_tool("get_medical_cards_by_date", {
            "date_from": "2026-07-03", "date_to": "2026-07-01",
        })
    assert snapshot_service_metrics()["tool_calls_total"][f"{LABEL}|error"] == 1


@pytest.mark.asyncio
async def test_single_day_timeout_requires_complete_restart(monkeypatch):
    async def get(_self, _path, **_kwargs):
        raise VetmanagerTimeoutError("Vetmanager request time budget was exhausted.")

    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    with headers, runtime, pytest.raises(ToolError) as failure:
        await mcp.call_tool("get_medical_cards_by_date", {
            "date": "2026-07-01", "offset": 20,
        })
    message = str(failure.value)
    assert "For any retry" in message
    assert "offset=0" in message and "all pages" in message
    assert "incomplete coverage" in message


@pytest.mark.asyncio
async def test_published_description_preserves_full_scope_on_timeout():
    tools = {tool.name: tool.to_mcp_tool().description for tool in await mcp.list_tools()}
    description = tools["get_medical_cards_by_date"]
    assert "offset=0" in description
    assert "each day" in description
    assert "creator_id" in description and "author" in description
    assert "get_medical_cards" in description and "date_create" in description


@pytest.mark.asyncio
async def test_slow_shared_metrics_do_not_delay_dated_cards(monkeypatch):
    release = Event()
    started = Event()

    class SlowBackend:
        def increment(self, *_args):
            started.set()
            release.wait(timeout=2)

        def observe(self, *_args):
            started.set()
            release.wait(timeout=2)

    async def get(_self, _path, **_kwargs):
        return {"success": True, "data": {"medicalCards": [], "totalCount": 0}}

    monkeypatch.setattr(shared_metric_counters, "get_backend", lambda: SlowBackend())
    monkeypatch.setattr(VetmanagerClient, "get", get)
    headers, runtime = _runtime()
    try:
        with headers, runtime:
            result = await asyncio.wait_for(
                mcp.call_tool("get_medical_cards_by_date", ARGS), timeout=0.5,
            )
        assert result.structured_content["medical_cards_count"] == 0
        assert started.wait(timeout=0.5)
    finally:
        release.set()
