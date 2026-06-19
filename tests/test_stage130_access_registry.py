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
    PRESET_REPORT_AI,
    TOKEN_PRESET_SCOPES,
    MARKETED_PRESET_TOOLS,
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    normalize_token_preset,
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
    SCOPE_REPORT_AI_WRITE,
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
                SCOPE_ANALYTICS_READ,
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
                SCOPE_ANALYTICS_READ,
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
        (
            PRESET_REPORT_AI,
            (
                SCOPE_ADMISSIONS_READ,
                SCOPE_ANALYTICS_READ,
                SCOPE_CLIENTS_READ,
                SCOPE_FINANCE_READ,
                SCOPE_INVENTORY_READ,
                SCOPE_MEDICAL_CARDS_READ,
                SCOPE_PETS_READ,
                SCOPE_REFERENCE_READ,
                SCOPE_REPORT_AI_WRITE,
                SCOPE_USERS_READ,
            ),
        ),
    ],
)
def test_presets_expose_expected_scope_bundles(preset, expected_scopes):
    assert TOKEN_PRESET_SCOPES[preset] == tuple(sorted(expected_scopes))


def test_marketed_preset_tools_are_covered_by_preset_scopes():
    for preset, tool_names in MARKETED_PRESET_TOOLS.items():
        preset_scopes = set(TOKEN_PRESET_SCOPES[preset])
        for tool_name in tool_names:
            assert set(TOOL_REQUIRED_SCOPES[tool_name]).issubset(preset_scopes)


def test_full_access_preset_covers_every_registered_tool_scope():
    full_access_scopes = set(TOKEN_PRESET_SCOPES[PRESET_FULL_ACCESS])
    for tool_name, required_scopes in TOOL_REQUIRED_SCOPES.items():
        assert set(required_scopes).issubset(full_access_scopes), tool_name


def test_frontdesk_accepts_analytics_read_blast_radius_explicitly():
    analytics_tools = {
        name
        for name, scopes in TOOL_REQUIRED_SCOPES.items()
        if SCOPE_ANALYTICS_READ in scopes
    }
    assert analytics_tools == {
        "confirm_report_ai_job_candidate",
        "create_report_ai_job",
        "get_doctor_free_slots",
        "get_message_reports",
        "get_report_ai_job_export",
        "get_report_ai_job",
        "get_report_ai_job_data",
        "get_report_export_file",
        "get_timesheet_by_id",
        "get_timesheets",
        "start_report_export",
    }
    assert SCOPE_ANALYTICS_READ in TOKEN_PRESET_SCOPES[PRESET_FRONTDESK]


@pytest.mark.parametrize("preset", ["unknown", " clinical_staff ", "   "])
def test_normalize_token_preset_rejects_unknown_or_whitespace_values(preset):
    with pytest.raises(ValueError, match="Unknown token access preset."):
        normalize_token_preset(preset)


@pytest.mark.parametrize(
    ("tool_name", "expected_scopes"),
    [
        ("get_client_profile", (SCOPE_CLIENTS_READ, SCOPE_FINANCE_READ, SCOPE_ADMISSIONS_READ)),
        ("get_personal_account_link_by_phone", (SCOPE_CLIENTS_READ,)),
        ("get_pet_profile", (SCOPE_PETS_READ, SCOPE_MEDICAL_CARDS_READ)),
        ("get_inactive_pets", (SCOPE_CLIENTS_READ, SCOPE_PETS_READ, SCOPE_FINANCE_READ, SCOPE_MEDICAL_CARDS_READ)),
        ("get_doctor_free_slots", (SCOPE_ADMISSIONS_READ, SCOPE_ANALYTICS_READ)),
        ("get_message_reports", (SCOPE_ANALYTICS_READ,)),
        ("create_report_ai_job", (SCOPE_ANALYTICS_READ,)),
        ("search_invoice_goods", (SCOPE_INVENTORY_READ,)),
        ("get_good_combination", (SCOPE_INVENTORY_READ,)),
        ("calculate_good_combination_price", (SCOPE_INVENTORY_READ,)),
        ("get_report_ai_job", (SCOPE_ANALYTICS_READ,)),
        ("confirm_report_ai_job_candidate", (SCOPE_ANALYTICS_READ,)),
        ("get_report_ai_job_data", (SCOPE_ANALYTICS_READ,)),
        ("start_report_export", (SCOPE_ANALYTICS_READ,)),
        ("get_report_export_file", (SCOPE_ANALYTICS_READ,)),
        ("get_report_ai_job_export", (SCOPE_ANALYTICS_READ,)),
        ("save_report_ai_job_as_report", (SCOPE_REPORT_AI_WRITE,)),
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
    assert required_scope_for_request("GET", "/rest/api/ClientPhone") == SCOPE_CLIENTS_READ
    assert required_scope_for_request("POST", "/rest/api/report-ai-job") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("GET", "/rest/api/report-ai-job/2") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("POST", "/rest/api/report-ai-job/2/confirm") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("GET", "/rest/api/report-ai-job/2/data") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("POST", "/rest/api/report-ai-job/2/save") == SCOPE_REPORT_AI_WRITE
    assert required_scope_for_request("GET", "/rest/api/report/StartReport") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("GET", "/rest/api/report/reportFile") == SCOPE_ANALYTICS_READ
    assert required_scope_for_request("GET", "/rest/api/good/productsDataForInvoice") == SCOPE_INVENTORY_READ
    assert required_scope_for_request("GET", "/rest/api/good/checkProductData") == SCOPE_INVENTORY_READ
    assert required_scope_for_request("GET", "/rest/api/goodTag") == SCOPE_INVENTORY_READ
    assert required_scope_for_request("GET", "/rest/api/VmLink/personalAccountLinkByPhone/79184140259") == SCOPE_CLIENTS_READ


def test_report_ai_preset_advertises_full_report_ai_flow():
    assert MARKETED_PRESET_TOOLS[PRESET_REPORT_AI] == (
        "create_report_ai_job",
        "confirm_report_ai_job_candidate",
        "get_report_ai_job",
        "get_report_ai_job_data",
        "start_report_export",
        "get_report_export_file",
        "get_report_ai_job_export",
        "save_report_ai_job_as_report",
    )
    assert get_presets_allowing_tool("save_report_ai_job_as_report") == (
        "Full access",
        "Analytics",
    )
