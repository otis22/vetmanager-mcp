"""Stage 311 — a shift that is «весь день» or ночная.

Vetmanager has carried `timesheet.all_day` and `timesheet.night` since the
table was created, and accepts any value in them: a live probe on the stand on
09.09.2026 took a row with both flags on, and a night shift that never crosses
midnight. Both are rows the interface cannot produce. Whatever meaning those
flags have is kept here or nowhere.
"""

import json

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

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


def _create_route():
    return respx.post(f"{BASE}/rest/api/timesheet").mock(
        return_value=httpx.Response(201, json={"data": {"id": 7}})
    )


def _update_route(timesheet_id: int = 7):
    return respx.put(f"{BASE}/rest/api/timesheet/{timesheet_id}").mock(
        return_value=httpx.Response(200, json={"data": {"id": timesheet_id}})
    )


BASE_SHIFT = {
    "doctor_id": 3,
    "begin_datetime": "2027-03-01T09:00:00",
    "end_datetime": "2027-03-01T18:00:00",
    "clinic_id": 1,
    "type": 2,
}


def _shift(**overrides) -> dict:
    return {**BASE_SHIFT, **overrides}


# --- creation ---------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_an_ordinary_shift_still_carries_no_flags():
    """Upstream defaults both fields to zero. Sending an explicit zero would
    mean writing down a decision the caller never made."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("create_timesheet", _shift())

    body = _body_of(route)
    assert "all_day" not in body
    assert "night" not in body


@pytest.mark.asyncio
@respx.mock
async def test_an_all_day_shift_takes_the_whole_day_not_the_hours_passed():
    """The shift form rewrites the times when the box is ticked, and
    `editSmena` reads the flag back out of them. A row flagged all-day with
    working hours inside it says two different things at once."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("create_timesheet", _shift(all_day=True))

    body = _body_of(route)
    assert body["all_day"] == 1
    assert body["begin_datetime"] == "2027-03-01 00:00:00"
    assert body["end_datetime"] == "2027-03-01 23:59:59"


@pytest.mark.asyncio
@respx.mock
async def test_an_all_day_shift_keeps_the_dates_it_was_given():
    """The interface sets the times on each end separately and leaves the
    dates alone, so a multi-day all-day span is a row it can produce."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_timesheet",
            _shift(
                begin_datetime="2027-03-01T09:00:00",
                end_datetime="2027-03-03T18:00:00",
                all_day=True,
            ),
        )

    body = _body_of(route)
    assert body["begin_datetime"] == "2027-03-01 00:00:00"
    assert body["end_datetime"] == "2027-03-03 23:59:59"


@pytest.mark.asyncio
@respx.mock
async def test_a_night_shift_crossing_midnight_is_created():
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_timesheet",
            _shift(
                begin_datetime="2027-03-01T20:00:00",
                end_datetime="2027-03-02T08:00:00",
                night=True,
            ),
        )

    body = _body_of(route)
    assert body["night"] == 1
    assert body["begin_datetime"] == "2027-03-01 20:00:00"
    assert body["end_datetime"] == "2027-03-02 08:00:00"


@pytest.mark.asyncio
@respx.mock
async def test_a_night_shift_inside_one_day_is_refused_before_the_call():
    """The stand accepted this row with a 201. A night shift that ends the day
    it started is a mislabelled day shift, and only we can say so."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool("create_timesheet", _shift(night=True))

    assert "night" in str(excinfo.value).lower()
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_a_night_shift_crossing_midnight_by_an_hour_is_accepted():
    """23:00 to 01:00 is two hours long and still a night shift: the rule is
    about the date it lands on, not about how long it runs."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "create_timesheet",
            _shift(
                begin_datetime="2027-03-01T23:00:00",
                end_datetime="2027-03-02T01:00:00",
                night=True,
            ),
        )

    assert _body_of(route)["night"] == 1


@pytest.mark.asyncio
@respx.mock
async def test_both_flags_at_once_are_refused_before_the_call():
    """The stand answered 201 to this pair. The interface clears one box when
    the other is ticked, so no such row exists to compare against."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool(
                "create_timesheet",
                _shift(
                    begin_datetime="2027-03-01T20:00:00",
                    end_datetime="2027-03-02T08:00:00",
                    all_day=True,
                    night=True,
                ),
            )

    message = str(excinfo.value).lower()
    assert "all_day" in message and "night" in message
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_a_shift_that_ends_before_it_starts_is_refused():
    """Neither schedule form saves this, and it needs no flag to be wrong."""
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "create_timesheet",
                _shift(
                    begin_datetime="2027-03-01T18:00:00",
                    end_datetime="2027-03-01T09:00:00",
                ),
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_a_shift_of_zero_length_is_refused():
    billing_mock()
    route = _create_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "create_timesheet",
                _shift(
                    begin_datetime="2027-03-01T09:00:00",
                    end_datetime="2027-03-01T09:00:00",
                ),
            )

    assert not route.called


# --- editing ----------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_turning_on_all_day_puts_out_the_night_flag():
    """What the interface does with the other checkbox. Without it we would
    produce the very pair creation refuses."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_timesheet",
            {
                "timesheet_id": 7,
                "begin_datetime": "2027-03-01T09:00:00",
                "end_datetime": "2027-03-01T18:00:00",
                "all_day": True,
            },
        )

    body = _body_of(route)
    assert body["all_day"] == 1
    assert body["night"] == 0
    assert body["begin_datetime"] == "2027-03-01 00:00:00"
    assert body["end_datetime"] == "2027-03-01 23:59:59"


@pytest.mark.asyncio
@respx.mock
async def test_turning_on_night_puts_out_the_all_day_flag():
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_timesheet",
            {
                "timesheet_id": 7,
                "begin_datetime": "2027-03-01T20:00:00",
                "end_datetime": "2027-03-02T08:00:00",
                "night": True,
            },
        )

    body = _body_of(route)
    assert body["night"] == 1
    assert body["all_day"] == 0


@pytest.mark.asyncio
@respx.mock
async def test_turning_a_flag_on_without_both_dates_is_refused():
    """Both flags redefine the times of the row, and the tool does not know
    what they currently are. Reading the row to find out would buy a request
    to check a value the caller has to state anyway."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool(
                "update_timesheet", {"timesheet_id": 7, "night": True}
            )

    assert "begin_datetime" in str(excinfo.value)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_turning_on_all_day_with_only_one_date_is_refused():
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "update_timesheet",
                {
                    "timesheet_id": 7,
                    "begin_datetime": "2027-03-01T09:00:00",
                    "all_day": True,
                },
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_taking_a_flag_off_needs_no_dates():
    """A zero says nothing about time, so it needs no time to say it."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_timesheet", {"timesheet_id": 7, "night": False}
        )

    body = _body_of(route)
    assert body == {"night": 0}


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_made_of_one_flag_is_not_an_empty_edit():
    """`update_timesheet` refuses an empty body because upstream answers 406.
    A flag is a change like any other."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "update_timesheet", {"timesheet_id": 7, "all_day": False}
        )

    assert route.called
    assert _body_of(route) == {"all_day": 0}


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_with_no_fields_at_all_is_still_refused():
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool("update_timesheet", {"timesheet_id": 7})

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_both_flags_at_once_are_refused_in_an_edit_too():
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "update_timesheet",
                {
                    "timesheet_id": 7,
                    "begin_datetime": "2027-03-01T20:00:00",
                    "end_datetime": "2027-03-02T08:00:00",
                    "all_day": True,
                    "night": True,
                },
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_that_ends_before_it_starts_is_refused():
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError):
            await mcp.call_tool(
                "update_timesheet",
                {
                    "timesheet_id": 7,
                    "begin_datetime": "2027-03-01T18:00:00",
                    "end_datetime": "2027-03-01T09:00:00",
                },
            )

    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_moving_one_end_only_is_refused():
    """The other boundary lives in the row, and the tool does not read it. A
    row edited to 20:00 that still ends at 18:00 is exactly the shift this
    stage refuses to create — the edit path must not be a way back in."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as excinfo:
            await mcp.call_tool(
                "update_timesheet",
                {"timesheet_id": 7, "end_datetime": "2027-03-01T20:00:00"},
            )

    assert "begin_datetime" in str(excinfo.value)
    assert not route.called


@pytest.mark.asyncio
@respx.mock
async def test_an_edit_that_touches_no_times_still_sends_only_what_changed():
    """Pairing is about the two boundaries of one interval, not about edits
    in general: everything else still travels alone."""
    billing_mock()
    route = _update_route()
    headers_patch, runtime_patch = bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool("update_timesheet", {"timesheet_id": 7, "type": 3})

    assert _body_of(route) == {"type": 3}
