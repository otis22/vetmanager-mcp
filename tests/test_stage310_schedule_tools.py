"""Stage 310 — the schedule tools do what they promise.

`create_timesheet` had never worked: Vetmanager's own controller refuses a
shift without `type` (`TimesheetController::doRestCreate`), and the tool
declared that field optional and left it out. Editing and deleting a shift did
not exist at all, so a spreadsheet loaded by mistake could only be cleaned up
by hand. And `type` is an id from a table nobody could read.
"""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError, ValidationError

from server import mcp
from tests.runtime_factories import patch_runtime_credentials

DOMAIN = "testclinic"
BASE = "https://testclinic.vetmanager.cloud"


def billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        "test-key-mock",
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def _body_of(route) -> dict:
    return json.loads(route.calls.last.request.content)


@pytest.mark.asyncio
@respx.mock
async def test_creating_a_shift_carries_the_type_upstream_requires():
    """Without `type` the controller answers 400 `type is not set`, so every
    call this tool made until now was refused before touching the schedule."""
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_timesheet",
            {
                "doctor_id": 3,
                "begin_datetime": "2027-03-01T09:00:00",
                "end_datetime": "2027-03-01T18:00:00",
                "clinic_id": 1,
                "type": 2,
            },
        )

    body = _body_of(route)
    assert body["type"] == 2
    # Required by the model too, and 0 is what every real row on the stand
    # carries. Leaving it out is what the model rejects, not the value.
    assert body["shedule_id"] == 0
    assert body["begin_datetime"] == "2027-03-01 09:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_a_shift_without_a_type_never_reaches_the_clinic():
    billing_mock()
    route = respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    # A missing required argument is rejected by argument validation, before
    # the body runs at all — which is the point: the call never leaves us.
    with headers_patch, runtime_patch, pytest.raises(ValidationError):
        await mcp.call_tool(
            "create_timesheet",
            {
                "doctor_id": 3,
                "begin_datetime": "2027-03-01T09:00:00",
                "end_datetime": "2027-03-01T18:00:00",
                "clinic_id": 1,
            },
        )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_editing_a_shift_sends_only_what_changed():
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/timesheet/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_timesheet",
            {"timesheet_id": 7, "end_datetime": "2027-03-01T20:00:00"},
        )

    body = _body_of(route)
    assert body == {"end_datetime": "2027-03-01 20:00:00"}


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_that_changes_nothing_is_refused_here():
    """`ERestController::saveModel` answers 406 `No params` to an empty body.
    Sending a request we know will be refused only costs the clinic a puzzle."""
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/timesheet/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch, pytest.raises(ToolError):
        await mcp.call_tool("update_timesheet", {"timesheet_id": 7})

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_sends_a_zero_it_was_given():
    """The tool promises to send the fields it is passed. Deciding that zero
    means "not passed" makes that promise false for whoever needs it — better
    to hand the value upstream and let it answer."""
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/timesheet/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("update_timesheet", {"timesheet_id": 7, "clinic_id": 0})

    assert _body_of(route) == {"clinic_id": 0}


@pytest.mark.asyncio
@respx.mock
async def test_a_title_can_be_cleared():
    """Upstream constrains the label's length, not its emptiness, so an empty
    title is a value — the one that removes a label typed by mistake."""
    billing_mock()
    route = respx.put(f"{BASE}/rest/api/timesheet/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("update_timesheet", {"timesheet_id": 7, "title": ""})

    assert _body_of(route) == {"title": ""}


@pytest.mark.asyncio
@respx.mock
async def test_deleting_a_shift_removes_it():
    billing_mock()
    route = respx.delete(f"{BASE}/rest/api/timesheet/7").mock(
        return_value=httpx.Response(200, json={"data": {"id": 7}})
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("delete_timesheet", {"timesheet_id": 7})

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_the_types_table_is_readable():
    """The path is case sensitive: `timesheettypes` answers 404 on the stand."""
    billing_mock()
    route = respx.get(f"{BASE}/rest/api/timesheetTypes").mock(
        return_value=httpx.Response(
            200,
            json={"data": {"totalCount": 1, "timesheetTypes": [{"id": 2, "name": "Рабочее время"}]}},
        )
    )
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("get_timesheet_types", {})

    assert route.called
