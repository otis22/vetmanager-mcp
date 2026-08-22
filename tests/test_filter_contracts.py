"""Stage-235 public raw-filter contract regressions."""

import json
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from filters import FILTER_FIELDS_BY_ENTITY, validate_filter_properties
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

def test_finance_filter_allowlists_match_real_probe_artifact():
    artifact = json.loads(
        (Path(__file__).parents[1] / "artifacts/filter-contracts-finance.json").read_text()
    )
    assert {
        entity: sorted(fields) for entity, fields in FILTER_FIELDS_BY_ENTITY.items()
    } == artifact["entities"]


def test_filter_validation_lists_allowed_properties():
    with pytest.raises(ValueError, match="Unknown filter property 'close_date'.*date"):
        validate_filter_properties(
            [{"property": "close_date", "operator": "=", "value": 1}],
            FILTER_FIELDS_BY_ENTITY["cassaclose"],
        )


def test_filter_validation_kill_switch_restores_passthrough(monkeypatch):
    monkeypatch.setenv("FILTER_CONTRACT_VALIDATION_ENABLED", "0")
    validate_filter_properties(
        [{"property": "close_date", "operator": "=", "value": 1}],
        FILTER_FIELDS_BY_ENTITY["cassaclose"],
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
