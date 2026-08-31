"""Stage 272 — a preset's tool list is computed, not written down twice.

The registry used to hold two answers to "what does this preset give": the real
one, enforced by the scope check, and a hand-written `MARKETED_PRESET_TOOLS`
that the refusal text quoted. They drifted — Analytics really gave 97 tools
while the list still said 8 — and the drift was invisible because the test only
checked that the written list was a subset of the real one.

The written list is gone. These tests pin the computed answer to the only rule
that matters: the one the call check applies.
"""

from types import SimpleNamespace

import pytest

from tool_access_registry import (
    BASELINE_ALLOWED_TOOLS,
    TOKEN_PRESET_CHOICES,
    TOKEN_PRESET_LABELS,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    tools_for_preset,
)
from tool_scope_security import ScopeDeniedToolError, _ensure_tool_scopes_allowed


@pytest.mark.parametrize("preset", TOKEN_PRESET_CHOICES)
def test_the_computed_list_is_what_the_call_check_allows(preset):
    computed = set(tools_for_preset(preset))
    credentials = SimpleNamespace(scopes=TOKEN_PRESET_SCOPES[preset])

    for tool_name in TOOL_REQUIRED_SCOPES:
        try:
            _ensure_tool_scopes_allowed(tool_name, credentials)
        except ScopeDeniedToolError:
            assert tool_name not in computed, f"{preset} advertises {tool_name} but refuses it"
        else:
            assert tool_name in computed, f"{preset} allows {tool_name} but does not list it"


def test_a_tool_with_no_rights_is_a_named_one_not_a_forgotten_one():
    """`required_scopes ⊆ preset_scopes` is true for an empty list, so a tool
    whose rights were never filled in would be advertised by every preset and
    refused on the call. The two sets have to be the same set."""
    unmapped = {name for name, scopes in TOOL_REQUIRED_SCOPES.items() if not scopes}

    assert unmapped == set(BASELINE_ALLOWED_TOOLS)


@pytest.mark.parametrize("preset", TOKEN_PRESET_CHOICES)
def test_tools_that_need_no_rights_belong_to_every_preset(preset):
    computed = set(tools_for_preset(preset))

    for name in BASELINE_ALLOWED_TOOLS:
        assert name in computed


def test_the_refusal_names_every_preset_that_would_work():
    """Understating the list is not a harmless slip: the refusal is what an
    agent reads, and a short list sends it asking for a wider key than the job
    needs."""
    for tool_name, required in TOOL_REQUIRED_SCOPES.items():
        if not required:
            continue
        granting = {
            TOKEN_PRESET_LABELS[preset]
            for preset in TOKEN_PRESET_CHOICES
            if set(required).issubset(set(TOKEN_PRESET_SCOPES[preset]))
        }

        assert set(get_presets_allowing_tool(tool_name)) == granting, tool_name


def test_analytics_covers_the_whole_report_flow():
    computed = set(tools_for_preset("report_ai"))

    for tool_name in (
        "create_report_ai_job",
        "confirm_report_ai_job_candidate",
        "get_report_ai_job",
        "get_report_ai_job_data",
        "save_report_ai_job_as_report",
        "start_report_export",
        "get_report_export_file",
        "get_report_ai_job_export",
    ):
        assert tool_name in computed, tool_name
