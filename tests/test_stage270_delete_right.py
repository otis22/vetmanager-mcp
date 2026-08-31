"""Stage 270 — deleting a record is its own right.

`delete_client` used to need `clients.write`: the same right as creating one.
So front desk, which is meant to register clients and pets, could also erase
them — and its advertised tool list never said so. Creating a record is undone
by editing it; deleting one is undone by nothing, so it now sits behind
`records.delete`, which only Full access carries.
"""

import json
from types import SimpleNamespace

import pytest

from tool_access_registry import (
    PRESET_FULL_ACCESS,
    TOKEN_PRESET_CHOICES,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
)
from tool_scope_security import ScopeDeniedToolError, _ensure_tool_scopes_allowed
from token_scopes import (
    SCOPE_CLIENTS_WRITE,
    SCOPE_PETS_WRITE,
    SCOPE_RECORDS_DELETE,
    SUPPORTED_TOKEN_SCOPES,
    deserialize_token_scopes,
    required_scope_for_request,
)

DELETING_TOOLS = ("delete_client", "delete_pet")
# What front desk is meant to do with the same records.
FRONTDESK_WRITING_TOOLS = ("create_client", "update_client", "create_pet", "update_pet")


def _credentials(preset):
    return SimpleNamespace(scopes=TOKEN_PRESET_SCOPES[preset])


@pytest.mark.parametrize("tool_name", DELETING_TOOLS)
def test_deleting_needs_the_delete_right(tool_name):
    assert TOOL_REQUIRED_SCOPES[tool_name] == (SCOPE_RECORDS_DELETE,)


@pytest.mark.parametrize("preset", [p for p in TOKEN_PRESET_CHOICES if p != PRESET_FULL_ACCESS])
@pytest.mark.parametrize("tool_name", DELETING_TOOLS)
def test_no_preset_but_full_access_can_delete(preset, tool_name):
    with pytest.raises(ScopeDeniedToolError):
        _ensure_tool_scopes_allowed(tool_name, _credentials(preset))


@pytest.mark.parametrize("tool_name", DELETING_TOOLS)
def test_full_access_still_deletes(tool_name):
    _ensure_tool_scopes_allowed(tool_name, _credentials(PRESET_FULL_ACCESS))


@pytest.mark.parametrize("tool_name", FRONTDESK_WRITING_TOOLS)
def test_front_desk_keeps_creating_and_editing(tool_name):
    _ensure_tool_scopes_allowed(tool_name, _credentials("frontdesk"))


def test_writing_rights_no_longer_carry_deletion():
    assert SCOPE_RECORDS_DELETE not in (SCOPE_CLIENTS_WRITE, SCOPE_PETS_WRITE)
    for preset, scopes in TOKEN_PRESET_SCOPES.items():
        if preset == PRESET_FULL_ACCESS:
            assert SCOPE_RECORDS_DELETE in scopes
        else:
            assert SCOPE_RECORDS_DELETE not in scopes, preset


@pytest.mark.parametrize(
    "path",
    [
        "/rest/api/client/5",
        "/rest/api/pet/5",
        # An entity no tool deletes today: the second layer must still refuse a
        # DELETE by default rather than wave it through as an unmapped path.
        "/rest/api/invoice/5",
        "/rest/api/Suppliers/5",
    ],
)
def test_the_second_layer_treats_every_delete_as_a_deletion(path):
    assert required_scope_for_request("DELETE", path) == SCOPE_RECORDS_DELETE


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/rest/api/client", SCOPE_CLIENTS_WRITE),
        ("PUT", "/rest/api/pet/5", SCOPE_PETS_WRITE),
    ],
)
def test_creating_and_editing_keep_their_own_rights(method, path, expected):
    assert required_scope_for_request(method, path) == expected


def test_a_full_access_key_issued_before_this_stage_still_deletes():
    """The stored list is what a key carries; a new right would leave it short.

    Without the snapshot, every Full access key issued until today would
    silently stop being full access.
    """
    issued_before = [scope for scope in SUPPORTED_TOKEN_SCOPES if scope != SCOPE_RECORDS_DELETE]

    restored = deserialize_token_scopes(json.dumps(issued_before))

    assert restored == list(SUPPORTED_TOKEN_SCOPES)
    assert SCOPE_RECORDS_DELETE in restored
