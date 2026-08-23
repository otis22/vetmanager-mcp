"""Stage-235 public raw-filter contract regressions."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from filters import (
    FILTER_FIELDS_BY_ENTITY, FilterPropertyValidationError, SortPropertyValidationError,
    validate_filter_properties, validate_sort_properties,
)
from service_metrics import snapshot_service_metrics
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def _runtime_patch():
    return patch_runtime_credentials(DOMAIN, API_KEY, bearer_token="mock-token")


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )

def test_filter_allowlists_match_real_probe_artifacts():
    artifact_dir = Path(__file__).parents[1] / "artifacts"
    artifacts = [
        json.loads((artifact_dir / "filter-contracts-finance.json").read_text()),
        json.loads((artifact_dir / "filter-contracts-list.json").read_text()),
    ]
    expected = {}
    for artifact in artifacts:
        excluded = artifact.get("public_excluded_fields", {})
        expected.update({
            entity: sorted(set(fields) - set(excluded.get(entity, [])))
            for entity, fields in artifact["entities"].items()
        })
    assert {
        entity: sorted(fields) for entity, fields in FILTER_FIELDS_BY_ENTITY.items()
    } == expected


def test_filter_validation_lists_allowed_properties():
    with pytest.raises(FilterPropertyValidationError, match="Unknown filter property 'close_date'.*date"):
        validate_filter_properties(
            [{"property": "close_date", "operator": "=", "value": 1}],
            FILTER_FIELDS_BY_ENTITY["cassaclose"],
        )
    assert snapshot_service_metrics()["business_events_total"]["filter_property_rejected"] == 1


def test_filter_validation_kill_switch_restores_passthrough(monkeypatch):
    monkeypatch.setenv("FILTER_CONTRACT_VALIDATION_ENABLED", "0")
    validate_filter_properties(
        [{"property": "close_date", "operator": "=", "value": 1}],
        FILTER_FIELDS_BY_ENTITY["cassaclose"],
    )
    assert "filter_property_rejected" not in snapshot_service_metrics()["business_events_total"]


def test_sort_validation_suggests_canonical_property_and_has_independent_switch(monkeypatch):
    with pytest.raises(SortPropertyValidationError, match="date_admission.*admission_date"):
        validate_sort_properties(
            [{"property": "date_admission", "direction": "ASC"}],
            FILTER_FIELDS_BY_ENTITY["admission"],
        )
    monkeypatch.setenv("SORT_CONTRACT_VALIDATION_ENABLED", "0")
    validate_sort_properties(
        [{"property": "date_admission", "direction": "ASC"}],
        FILTER_FIELDS_BY_ENTITY["admission"],
    )


@pytest.mark.asyncio
@respx.mock
async def test_get_cassa_closes_rejects_incident_filter_before_http():
    route = respx.get(f"{BASE}/rest/api/cassaclose").mock(
        return_value=httpx.Response(200, json={"data": {"cassaclose": []}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="close_date.*date"):
            await mcp.call_tool(
                "get_cassa_closes",
                {"filter": [{"property": "close_date", "operator": "=", "value": "x"}]},
            )

    assert not route.called
    assert snapshot_service_metrics()["business_events_total"]["filter_property_rejected"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_get_admissions_rejects_incident_sort_before_http_with_canonical_hint():
    route = respx.get(f"{BASE}/rest/api/admission").mock(
        return_value=httpx.Response(200, json={"data": {"admission": []}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="Did you mean 'admission_date'\\?"):
            await mcp.call_tool(
                "get_admissions",
                {"sort": [{"property": "date_admission", "direction": "ASC"}]},
            )
    assert not route.called


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "endpoint", "property_name"),
    [("get_users", "/rest/api/user", "passwd"), ("get_clients", "/rest/api/client", "passport_series")],
)
@respx.mock
async def test_sensitive_sort_properties_are_rejected_before_http(tool_name, endpoint, property_name):
    route = respx.get(f"{BASE}{endpoint}").mock(return_value=httpx.Response(200, json={"data": {}}))
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match=property_name):
            await mcp.call_tool(tool_name, {"sort": [{"property": property_name, "direction": "ASC"}]})
    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("tool_name", "endpoint"),
    [
        ("get_payments", "/rest/api/payment"),
        ("get_invoices", "/rest/api/invoice"),
    ],
)
async def test_other_finance_tools_reject_unknown_filter_before_http(tool_name, endpoint):
    route = respx.get(f"{BASE}{endpoint}").mock(
        return_value=httpx.Response(200, json={"data": {}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="close_date"):
            await mcp.call_tool(
                tool_name,
                {"filter": [{"property": "close_date", "operator": "=", "value": "x"}]},
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("tool_name", "endpoint", "entity", "property_name"),
    [
        ("get_cassa_closes", "/rest/api/cassaclose", "cassaclose", "date"),
        ("get_payments", "/rest/api/payment", "payment", "parent_id"),
        ("get_invoices", "/rest/api/invoice", "invoice", "fiscal_section_id"),
    ],
)
async def test_finance_tools_preserve_confirmed_raw_filter(
    tool_name, endpoint, entity, property_name
):
    _billing_mock()
    route = respx.get(f"{BASE}{endpoint}").mock(
        return_value=httpx.Response(200, json={"data": {entity: []}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            tool_name,
            {"filter": [{"property": property_name, "operator": "=", "value": 1}]},
        )

    assert route.called


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    ("tool_name", "endpoint", "entity", "arguments"),
    [
        ("get_payments", "/rest/api/payment", "payment", {"date_from": "2026-01-01"}),
        ("get_invoices", "/rest/api/invoice", "invoice", {"client_id": 1}),
    ],
)
async def test_named_finance_filters_stay_within_verified_contract(
    tool_name, endpoint, entity, arguments
):
    _billing_mock()
    route = respx.get(f"{BASE}{endpoint}").mock(
        return_value=httpx.Response(200, json={"data": {entity: []}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(tool_name, arguments)

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_goods_keeps_name_extra_parameter_with_filter_validation():
    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/good").mock(
        return_value=httpx.Response(200, json={"data": {"good": []}})
    )
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_goods",
            {
                "name": "legacy name",
                "filter": [{"property": "title", "operator": "=", "value": "x"}],
            },
        )

    assert route.called
    assert route.calls[0].request.url.params["name"] == "legacy name"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_name", "endpoint", "property_name"),
    [
        ("get_users", "/rest/api/user", "passwd"),
        ("get_clients", "/rest/api/client", "passport_series"),
    ],
)
@respx.mock
async def test_sensitive_filter_properties_are_rejected_before_http(
    tool_name, endpoint, property_name
):
    route = respx.get(f"{BASE}{endpoint}").mock(return_value=httpx.Response(200, json={"data": {}}))
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match=property_name):
            await mcp.call_tool(
                tool_name,
                {"filter": [{"property": property_name, "operator": "LIKE", "value": "a%"}]},
            )
    assert not route.called
