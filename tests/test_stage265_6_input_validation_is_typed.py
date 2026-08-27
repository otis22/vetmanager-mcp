"""Stage 265.6: the caller's own mistake must not look like our defect.

Validation inside the tools was phrased as `clinic_id must be a positive
integer`. The rule that decided "do not offer to file a bug report" matched
prefixes `invalid ` / `missing `, so it never matched any of these — from the
first day, a typo in an argument came back with an invitation to report a
defect, and went to Sentry as a tool failure.

These tests go through the same boundary the agent enters, because that is the
only place where the invitation is attached.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from exceptions import ToolInputError
from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from tool_error_tracking import ToolErrorTrackingMiddleware


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


# Every one of these is the caller getting an argument wrong. None of them is
# a defect in this service, so none of them may invite a bug report.
BAD_ARGUMENTS = [
    ("get_good_combination", {"tag_id": 0, "clinic_id": 1}),
    ("get_good_combination", {"tag_id": 5, "clinic_id": 0}),
    ("calculate_good_combination_price", {"tag_id": 0}),
    ("calculate_good_combination_price", {"tag_id": 5, "quantity": 0}),
    ("calculate_good_combination_price", {"tag_id": 5, "clinic_id": -1}),
    ("search_invoice_goods", {"query": "x", "clinic_id": 0}),
    ("get_personal_account_link_by_phone", {"phone": "12345"}),
    ("create_report_ai_job", {"intent_text": "   "}),
    ("create_report_ai_job", {"intent_text": "a" * 20_001}),
    ("start_report_export", {"report_id": 0}),
    ("start_report_export", {"report_id": 7, "filter_json": "{not json"}),
    ("get_report_export_file", {"report_file_id": -3}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name,arguments", BAD_ARGUMENTS)
@respx.mock
async def test_a_wrong_argument_never_asks_the_user_to_report_a_defect(tool_name, arguments):
    _billing_mock()
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        augment = AsyncMock(return_value=ToolError("...and please report this problem."))
        with patch("tools.augment_tool_error", augment):
            with pytest.raises(ToolInputError):
                await mcp.call_tool(tool_name, arguments)
    augment.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_a_combination_that_does_not_exist_is_the_callers_id_not_our_bug():
    """The tag_id came from the caller; an empty answer for it is not a defect."""
    _billing_mock()
    respx.get(f"{BASE}/rest/api/goodTag").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"goodTag": []}}),
    )
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        augment = AsyncMock(return_value=ToolError("...and please report this problem."))
        with patch("tools.augment_tool_error", augment):
            with pytest.raises(ToolInputError):
                await mcp.call_tool("get_good_combination", {"tag_id": 4242, "clinic_id": 1})
    augment.assert_not_called()


@pytest.mark.asyncio
@respx.mock
async def test_a_broken_upstream_answer_still_asks_for_a_report():
    """The same validator runs on data we received. That must stay reportable.

    `_validate_positive_int` guards both the caller's `job_id` and the
    `report_id` that Vetmanager puts into the job. Typing the second one as an
    input error would blame the caller for our upstream's broken payload.
    """
    _billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/7").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"job": {"id": 7, "status": "saved", "report_id": "not-a-number"}},
        }),
    )
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as raised:
            await mcp.call_tool("get_report_ai_job_export", {"job_id": 7})
    assert not isinstance(raised.value, ToolInputError)


@pytest.mark.asyncio
async def test_an_input_error_is_not_a_tool_failure_for_sentry():
    """Live evidence 27.08.2026: PYTHON-Y is `ToolInputError: Invalid feedback severity.`

    The type said "the caller's mistake" and Sentry opened an issue anyway,
    because only the report hint was reading the type.
    """
    middleware = ToolErrorTrackingMiddleware()
    input_error = ToolInputError("clinic_id must be a positive integer.")

    async def fail(_context):
        raise input_error

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(ToolInputError):
            await middleware.on_call_tool(
                SimpleNamespace(message=SimpleNamespace(name="get_good_combination")), fail,
            )

    capture.assert_not_called()


@pytest.mark.asyncio
async def test_a_real_failure_is_still_captured():
    middleware = ToolErrorTrackingMiddleware()
    tool_error = ToolError("Upstream API error (HTTP 500).")

    async def fail(_context):
        raise tool_error

    with patch("tool_error_tracking.capture_tool_failure") as capture:
        with pytest.raises(ToolError):
            await middleware.on_call_tool(
                SimpleNamespace(message=SimpleNamespace(name="get_goods")), fail,
            )

    capture.assert_called_once()


def _rest_denied_payload() -> dict:
    return {"success": False, "message": "Report is not accessible for REST"}


@pytest.mark.asyncio
@respx.mock
async def test_a_report_the_caller_picked_is_the_callers_precondition():
    """`start_report_export` documents that the report must have REST export on.

    Sentry issue PYTHON-N is this exact refusal, filed against us twice.
    """
    _billing_mock()
    respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(403, json=_rest_denied_payload()),
    )
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        with pytest.raises(ToolInputError):
            await mcp.call_tool("start_report_export", {"report_id": 4242})


@pytest.mark.asyncio
@respx.mock
async def test_the_same_refusal_on_a_report_we_chose_is_still_reportable():
    """Here the report_id came out of the job, so the choice was not the caller's."""
    _billing_mock()
    respx.get(f"{BASE}/rest/api/report-ai-job/7").mock(
        return_value=httpx.Response(200, json={
            "success": True,
            "data": {"job": {"id": 7, "status": "saved", "report_id": 99}},
        }),
    )
    respx.get(f"{BASE}/rest/api/report/StartReport").mock(
        return_value=httpx.Response(403, json=_rest_denied_payload()),
    )
    headers_patch, runtime_patch = patch_runtime_credentials(DOMAIN, API_KEY)
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError) as raised:
            await mcp.call_tool("get_report_ai_job_export", {"job_id": 7})
    assert not isinstance(raised.value, ToolInputError)
