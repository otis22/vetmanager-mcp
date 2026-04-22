"""Stage 130.1 — tool access registry and preset matrix coverage."""

import pytest

from server import mcp
from tool_access_registry import (
    PRESET_DOCTOR,
    PRESET_FINANCE,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_INVENTORY,
    PRESET_READ_ONLY,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
)
from token_scopes import (
    SCOPE_ADMISSIONS_READ,
    SCOPE_ADMISSIONS_WRITE,
    SCOPE_ANALYTICS_READ,
    SCOPE_ANALYTICS_WRITE,
    SCOPE_CLIENTS_READ,
    SCOPE_CLIENTS_WRITE,
    SCOPE_FINANCE_READ,
    SCOPE_FINANCE_WRITE,
    SCOPE_INVENTORY_READ,
    SCOPE_INVENTORY_WRITE,
    SCOPE_MEDICAL_CARDS_READ,
    SCOPE_MEDICAL_CARDS_WRITE,
    SCOPE_MESSAGING_WRITE,
    SCOPE_PETS_READ,
    SCOPE_PETS_WRITE,
    SCOPE_REFERENCE_READ,
    SCOPE_USERS_READ,
    SCOPE_USERS_WRITE,
    SUPPORTED_TOKEN_SCOPES,
    required_scope_for_request,
)


async def _get_registered_tool_names() -> list[str]:
    tools = await mcp.list_tools()
    return sorted(tool.name for tool in tools)


@pytest.mark.asyncio
async def test_every_registered_tool_has_explicit_access_mapping():
    registered = await _get_registered_tool_names()
    missing = [name for name in registered if name not in TOOL_REQUIRED_SCOPES]
    extra = [name for name in TOOL_REQUIRED_SCOPES if name not in registered]

    assert not missing, f"Tools without access mapping: {missing}"
    assert not extra, f"Stale tool mappings for unregistered tools: {extra}"


def test_full_access_preset_matches_supported_scopes_snapshot():
    assert TOKEN_PRESET_SCOPES[PRESET_FULL_ACCESS] == tuple(sorted(SUPPORTED_TOKEN_SCOPES))


@pytest.mark.parametrize(
    ("preset", "expected_scopes"),
    [
        (
            PRESET_READ_ONLY,
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ANALYTICS_READ,
                SCOPE_CLIENTS_READ,
                SCOPE_FINANCE_READ,
                SCOPE_INVENTORY_READ,
                SCOPE_MEDICAL_CARDS_READ,
                SCOPE_PETS_READ,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            ),
        ),
        (
            PRESET_FRONTDESK,
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ADMISSIONS_WRITE,
                SCOPE_CLIENTS_READ,
                SCOPE_CLIENTS_WRITE,
                SCOPE_FINANCE_READ,
                SCOPE_MESSAGING_WRITE,
                SCOPE_PETS_READ,
                SCOPE_PETS_WRITE,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            ),
        ),
        (
            PRESET_DOCTOR,
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_MEDICAL_CARDS_READ,
                SCOPE_MEDICAL_CARDS_WRITE,
                SCOPE_PETS_READ,
                SCOPE_REFERENCE_READ,
                SCOPE_USERS_READ,
            ),
        ),
        (
            PRESET_FINANCE,
            (
                SCOPE_CLIENTS_READ,
                SCOPE_FINANCE_READ,
                SCOPE_FINANCE_WRITE,
                SCOPE_REFERENCE_READ,
            ),
        ),
        (
            PRESET_INVENTORY,
            (
                SCOPE_INVENTORY_READ,
                SCOPE_INVENTORY_WRITE,
                SCOPE_REFERENCE_READ,
            ),
        ),
    ],
)
def test_presets_expose_expected_scope_bundles(preset, expected_scopes):
    for scope in expected_scopes:
        assert scope in TOKEN_PRESET_SCOPES[preset]


@pytest.mark.parametrize(
    ("tool_name", "expected_scopes"),
    [
        ("get_client_profile", (SCOPE_CLIENTS_READ, SCOPE_FINANCE_READ, SCOPE_ADMISSIONS_READ)),
        ("get_pet_profile", (SCOPE_PETS_READ, SCOPE_MEDICAL_CARDS_READ)),
        ("get_inactive_pets", (SCOPE_CLIENTS_READ, SCOPE_PETS_READ, SCOPE_FINANCE_READ, SCOPE_MEDICAL_CARDS_READ)),
        ("get_doctor_free_slots", (SCOPE_ADMISSIONS_READ, SCOPE_ANALYTICS_READ)),
        ("get_message_reports", (SCOPE_ANALYTICS_READ,)),
        ("send_message_to_users", (SCOPE_MESSAGING_WRITE,)),
        ("update_user", (SCOPE_USERS_WRITE,)),
        ("create_timesheet", (SCOPE_ANALYTICS_WRITE,)),
    ],
)
def test_representative_tools_have_expected_scope_mapping(tool_name, expected_scopes):
    assert set(TOOL_REQUIRED_SCOPES[tool_name]) == set(expected_scopes)


def test_request_scope_mapping_covers_missing_write_paths():
    assert required_scope_for_request("PUT", "/rest/api/user/5") == SCOPE_USERS_WRITE
    assert required_scope_for_request("POST", "/rest/api/timesheet") == SCOPE_ANALYTICS_WRITE
    assert required_scope_for_request("GET", "/rest/api/messages/reports") == SCOPE_ANALYTICS_READ
