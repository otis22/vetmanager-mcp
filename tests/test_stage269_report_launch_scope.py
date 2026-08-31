"""Stage 269 — starting a report is a separate right from reading analytics.

`create_report_ai_job` takes free-form text and Vetmanager builds a report from
whatever clinic data answers it. While that tool sat on `analytics.read`, a
front-desk token that was refused `get_medical_cards` could ask for the same
medical cards as a report: our scopes do not travel with the generated query.

So everything that *starts* work upstream now lives on `report_ai.write`, the
right that only Analytics and Full access carry. Reading a job that already
exists stays on `analytics.read`.
"""

from types import SimpleNamespace

import pytest

from tool_access_registry import (
    PRESET_DOCTOR,
    PRESET_FRONTDESK,
    PRESET_FULL_ACCESS,
    PRESET_READ_ONLY,
    PRESET_REPORT_AI,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
    tools_for_preset,
)
from tool_scope_security import ScopeDeniedToolError, _ensure_tool_scopes_allowed
from token_scopes import (
    SCOPE_ANALYTICS_READ,
    SCOPE_REPORT_AI_WRITE,
    required_scope_for_request,
)

# Tools that make Vetmanager do something: create a job, move it forward, or
# start an export. `get_report_ai_job_export` is named like a reader and is not
# one — it starts an export for a saved job.
LAUNCHING_TOOLS = (
    "create_report_ai_job",
    "confirm_report_ai_job_candidate",
    "start_report_export",
    "get_report_ai_job_export",
    "save_report_ai_job_as_report",
)

# Tools that only look at what already exists.
READING_TOOLS = (
    "get_report_ai_job",
    "get_report_ai_job_data",
    "get_report_export_file",
)

PRESETS_WITHOUT_REPORT_RIGHTS = (PRESET_READ_ONLY, PRESET_FRONTDESK, PRESET_DOCTOR)
PRESETS_WITH_REPORT_RIGHTS = (PRESET_REPORT_AI, PRESET_FULL_ACCESS)


def _credentials(preset):
    return SimpleNamespace(scopes=TOKEN_PRESET_SCOPES[preset])


@pytest.mark.parametrize("tool_name", LAUNCHING_TOOLS)
def test_launching_a_report_requires_the_report_right(tool_name):
    assert TOOL_REQUIRED_SCOPES[tool_name] == (SCOPE_REPORT_AI_WRITE,)


@pytest.mark.parametrize("tool_name", READING_TOOLS)
def test_reading_a_report_stays_on_analytics_read(tool_name):
    assert TOOL_REQUIRED_SCOPES[tool_name] == (SCOPE_ANALYTICS_READ,)


@pytest.mark.parametrize("preset", PRESETS_WITHOUT_REPORT_RIGHTS)
@pytest.mark.parametrize("tool_name", LAUNCHING_TOOLS)
def test_a_preset_without_the_report_right_cannot_start_one(preset, tool_name):
    with pytest.raises(ScopeDeniedToolError):
        _ensure_tool_scopes_allowed(tool_name, _credentials(preset))


@pytest.mark.parametrize("preset", PRESETS_WITHOUT_REPORT_RIGHTS)
@pytest.mark.parametrize("tool_name", READING_TOOLS)
def test_those_presets_still_read_a_report_that_exists(preset, tool_name):
    if SCOPE_ANALYTICS_READ not in TOKEN_PRESET_SCOPES[preset]:
        pytest.skip(f"{preset} has no analytics.read at all")
    _ensure_tool_scopes_allowed(tool_name, _credentials(preset))


@pytest.mark.parametrize("preset", PRESETS_WITH_REPORT_RIGHTS)
@pytest.mark.parametrize("tool_name", LAUNCHING_TOOLS + READING_TOOLS)
def test_analytics_and_full_access_keep_the_whole_flow(preset, tool_name):
    _ensure_tool_scopes_allowed(tool_name, _credentials(preset))


@pytest.mark.parametrize(
    ("method", "path", "expected_scope"),
    [
        ("POST", "/rest/api/report-ai-job", SCOPE_REPORT_AI_WRITE),
        ("POST", "/rest/api/report-ai-job/2/confirm", SCOPE_REPORT_AI_WRITE),
        ("POST", "/rest/api/report-ai-job/2/save", SCOPE_REPORT_AI_WRITE),
        ("GET", "/rest/api/report/StartReport", SCOPE_REPORT_AI_WRITE),
        ("GET", "/rest/api/report/reportFile", SCOPE_ANALYTICS_READ),
        ("GET", "/rest/api/report-ai-job/2", SCOPE_ANALYTICS_READ),
        ("GET", "/rest/api/report-ai-job/2/data", SCOPE_ANALYTICS_READ),
    ],
)
def test_the_second_layer_splits_the_same_way(method, path, expected_scope):
    """Otherwise the tool check would be the only thing standing in the way."""
    assert required_scope_for_request(method, path) == expected_scope


@pytest.mark.parametrize("preset", PRESETS_WITHOUT_REPORT_RIGHTS)
def test_those_presets_no_longer_advertise_starting_a_report(preset):
    advertised = set(tools_for_preset(preset))
    promised_but_denied = sorted(advertised.intersection(LAUNCHING_TOOLS))
    assert not promised_but_denied, (
        f"preset {preset} still advertises {promised_but_denied}, which it can no longer do"
    )
