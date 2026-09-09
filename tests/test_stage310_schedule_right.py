"""Stage 310 — the work schedule gets its own right and a full set of operations.

A clinic asked to load its schedule from a spreadsheet and was told it needed
"write and delete on everything about the planner". The rights were never the
problem: creating a shift is rejected by Vetmanager itself, editing and
deleting a shift did not exist, and the one right that covered writing the
schedule was `analytics.write` — a name that says analytics, carries nothing
else, and lives only inside Full access. Asking a clinic to take a key that
deletes clients so it can add a shift is not an access model.
"""

import json
from types import SimpleNamespace

import pytest

from access_summary import NOTHING, summarize_access
from tool_access_registry import (
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_READ_ONLY,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
)
from tool_scope_security import ScopeDeniedToolError, _ensure_tool_scopes_allowed
from token_scopes import (
    SCOPE_ANALYTICS_WRITE,
    SCOPE_RECORDS_DELETE,
    SCOPE_REFERENCE_READ,
    SCOPE_SCHEDULE_WRITE,
    SUPPORTED_TOKEN_SCOPES,
    deserialize_token_scopes,
    required_scope_for_request,
)

SCHEDULE_TOOLS = ("create_timesheet", "update_timesheet", "delete_timesheet")
# What front desk must keep being unable to do, right alongside the new power.
RECORD_DELETING_TOOLS = ("delete_client", "delete_pet")


def _credentials(preset):
    return SimpleNamespace(scopes=TOKEN_PRESET_SCOPES[preset])


def test_the_schedule_has_a_right_of_its_own():
    assert SCOPE_SCHEDULE_WRITE in SUPPORTED_TOKEN_SCOPES


@pytest.mark.parametrize("tool_name", SCHEDULE_TOOLS)
def test_every_schedule_tool_asks_for_the_schedule_right(tool_name):
    assert TOOL_REQUIRED_SCOPES[tool_name] == (SCOPE_SCHEDULE_WRITE,)


def test_the_stale_right_carries_no_tools():
    """`analytics.write` stays supported so old key manifests still parse.

    It must stay empty, though: a right that still opens something is a second
    door to the schedule, and nobody would think to look for it here.
    """
    holders = [
        tool for tool, scopes in TOOL_REQUIRED_SCOPES.items() if SCOPE_ANALYTICS_WRITE in scopes
    ]

    assert holders == []


@pytest.mark.parametrize("tool_name", SCHEDULE_TOOLS)
def test_front_desk_runs_the_schedule(tool_name):
    _ensure_tool_scopes_allowed(tool_name, _credentials(PRESET_FRONTDESK))


@pytest.mark.parametrize("tool_name", RECORD_DELETING_TOOLS)
def test_front_desk_still_erases_no_records(tool_name):
    """The point of the whole stage: deleting a shift is not deleting a client."""
    with pytest.raises(ScopeDeniedToolError):
        _ensure_tool_scopes_allowed(tool_name, _credentials(PRESET_FRONTDESK))


@pytest.mark.parametrize("tool_name", SCHEDULE_TOOLS)
def test_read_only_does_not_touch_the_schedule(tool_name):
    with pytest.raises(ScopeDeniedToolError):
        _ensure_tool_scopes_allowed(tool_name, _credentials(PRESET_READ_ONLY))


@pytest.mark.parametrize("method", ["POST", "PUT"])
def test_the_second_layer_sends_schedule_writes_to_the_schedule_right(method):
    assert required_scope_for_request(method, "/rest/api/timesheet") == SCOPE_SCHEDULE_WRITE


def test_deleting_a_shift_asks_for_the_schedule_right():
    assert required_scope_for_request("DELETE", "/rest/api/timesheet/5") == SCOPE_SCHEDULE_WRITE


@pytest.mark.parametrize(
    "path",
    [
        "/rest/api/client/5",
        "/rest/api/pet/5",
        "/rest/api/invoice/5",
        # An entity the mapping has never heard of: the default must hold, or
        # this stage turns stage 270's fail-closed guard into a hole.
        "/rest/api/somethingNew/5",
    ],
)
def test_deleting_anything_else_still_asks_for_the_record_right(path):
    assert required_scope_for_request("DELETE", path) == SCOPE_RECORDS_DELETE


def test_the_types_reference_is_a_reference():
    """`type` is an id from a table, not a free value, so reading that table
    must not need more than any other reference does."""
    assert TOOL_REQUIRED_SCOPES["get_timesheet_types"] == (SCOPE_REFERENCE_READ,)
    assert required_scope_for_request("GET", "/rest/api/timesheetTypes") == SCOPE_REFERENCE_READ


def test_a_front_desk_key_issued_before_this_stage_gains_the_schedule():
    """A key carries the manifest stored when it was issued, so adding a right
    to the preset does not reach keys already in clinics' hands."""
    issued_before = [
        scope for scope in TOKEN_PRESET_SCOPES[PRESET_FRONTDESK] if scope != SCOPE_SCHEDULE_WRITE
    ]

    restored = deserialize_token_scopes(json.dumps(issued_before))

    assert SCOPE_SCHEDULE_WRITE in restored


def test_a_full_access_key_issued_before_this_stage_gains_the_schedule():
    """Full access means every right, so a key issued yesterday must gain this
    one too — otherwise "full access" quietly stops being full.

    Stated as this stage's own gap on purpose. The guard in stage 270 walks
    the list of snapshots, so deleting a snapshot deletes its own case and the
    check passes on a smaller list: it goes blind together with what it
    guards. This assertion names the composition that must be recognised, and
    fails when the snapshot for it is gone.
    """
    issued_before = [scope for scope in SUPPORTED_TOKEN_SCOPES if scope != SCOPE_SCHEDULE_WRITE]

    restored = deserialize_token_scopes(json.dumps(issued_before))

    assert SCOPE_SCHEDULE_WRITE in restored


def test_a_hand_edited_key_is_left_alone():
    """Top-up recognises one exact old composition. A key whose rights were
    trimmed by hand is not that composition, and must not quietly grow."""
    trimmed = [
        scope
        for scope in TOKEN_PRESET_SCOPES[PRESET_FRONTDESK]
        if scope not in (SCOPE_SCHEDULE_WRITE, SCOPE_RECORDS_DELETE)
    ][:-1]

    restored = deserialize_token_scopes(json.dumps(trimmed))

    assert SCOPE_SCHEDULE_WRITE not in restored


def _delete_line(preset):
    return dict(summarize_access(TOKEN_PRESET_SCOPES[preset]))["Удаление"]


def test_the_summary_admits_front_desk_deletes_shifts():
    """Stage 273 put this line on the screen precisely so a clinic owner could
    trust it. A key that erases shifts while the page says "Удаление: нет"
    breaks the promise the line was made for."""
    line = _delete_line(PRESET_FRONTDESK)

    assert line != NOTHING
    assert "смены" in line


def test_the_summary_keeps_records_and_shifts_apart():
    assert "клиенты" not in _delete_line(PRESET_FRONTDESK)
    assert "клиенты" in _delete_line(PRESET_FULL_ACCESS)
    assert "смены" in _delete_line(PRESET_FULL_ACCESS)


def test_read_only_still_deletes_nothing():
    assert _delete_line(PRESET_READ_ONLY) == NOTHING
