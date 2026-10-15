"""The public timesheet arguments must reach REST with inclusive day bounds."""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


BASE = "https://testclinic.vetmanager.cloud"


async def _call(arguments):
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )
    route = respx.get(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(200, json={"data": {"timesheet": []}})
    )
    headers, runtime = patch_runtime_credentials(
        "testclinic", "test-key-mock", bearer_token="mock-token",
        bearer_token_id=1, connection_id=1,
    )
    with headers, runtime:
        await mcp.call_tool("get_timesheets", arguments)
    return route


@pytest.mark.asyncio
@respx.mock
async def test_default_sort_is_newest_first_on_wire():
    route = await _call({})
    assert json.loads(route.calls.last.request.url.params["sort"]) == [
        {"property": "begin_datetime", "direction": "DESC"},
        {"property": "id", "direction": "DESC"},
    ]


@pytest.mark.asyncio
@respx.mock
async def test_explicit_empty_sort_keeps_upstream_order():
    route = await _call({"sort": []})
    assert "sort" not in route.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_range_adds_overlap_bounds_to_raw_filter_without_replacing_sort():
    raw = {"property": "clinic_id", "operator": "=", "value": 4}
    explicit_sort = [{"property": "id", "direction": "ASC"}]
    route = await _call({
        "date_from": "2026-10-01", "date_to": "2026-10-03", "doctor_id": 7,
        "filter": [raw], "sort": explicit_sort,
    })
    query = route.calls.last.request.url.params
    assert json.loads(query["sort"]) == explicit_sort
    assert json.loads(query["filter"]) == [
        raw,
        {"property": "doctor_id", "value": 7, "operator": "="},
        {"property": "end_datetime", "value": "2026-10-01 00:00:00", "operator": ">"},
        {"property": "begin_datetime", "value": "2026-10-04 00:00:00", "operator": "<"},
    ]
    assert "date_from" not in query and "date_to" not in query


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("arguments,expected", [
    ({"date_from": "2026-10-01"}, {"property": "end_datetime", "value": "2026-10-01 00:00:00", "operator": ">"}),
    ({"date_to": "2026-10-03"}, {"property": "begin_datetime", "value": "2026-10-04 00:00:00", "operator": "<"}),
])
async def test_each_range_boundary_works_alone(arguments, expected):
    route = await _call(arguments)
    assert json.loads(route.calls.last.request.url.params["filter"]) == [expected]


@pytest.mark.asyncio
@respx.mock
async def test_existing_date_intersects_with_new_range():
    route = await _call({"date": "2026-10-02", "date_from": "2026-10-01"})
    filters = json.loads(route.calls.last.request.url.params["filter"])
    assert {"property": "begin_datetime", "value": "2026-10-03 00:00:00", "operator": "<"} in filters
    assert {"property": "end_datetime", "value": "2026-10-02 00:00:00", "operator": ">"} in filters
    assert {"property": "end_datetime", "value": "2026-10-01 00:00:00", "operator": ">"} in filters


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("arguments", [
    {"date_from": "2026-02-30"},
    {"date_to": "9999-12-31"},
    {"date_from": "2026-10-04", "date_to": "2026-10-03"},
])
async def test_invalid_range_is_rejected_before_http(arguments):
    with pytest.raises((ToolError, ValueError), match="date"):
        await _call(arguments)
    assert all("/rest/api/timesheet" not in str(call.request.url) for call in respx.calls)
