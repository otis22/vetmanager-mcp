"""Rendered first-session contract and mutation guards for token-specific routes."""

import os

import pytest
from fastmcp import Client

from server import mcp
from tool_access_registry import TOKEN_PRESET_SCOPES, get_presets_granting_scope
from tool_scope_security import visible_tools_for_scopes


MUTATION = os.environ.get("STAGE377_MUTATION", "")
CHAIN = {"create_report_ai_job", "get_report_ai_job", "save_report_ai_job_as_report", "get_report_ai_job_data"}


def _mutate(body: str, instructions: str, names: set[str]):
    if MUTATION == "force_full_without_create":
        body = body.replace("only when the catalogue contains", "even when the catalogue lacks")
    elif MUTATION == "premature_create":
        body = body.replace("never try create_report_ai_job to test access", "try create_report_ai_job to test access")
    elif MUTATION == "remove_read_route":
        body = body.replace("Read route: choose a safe read tool", "Skip the read route: choose a safe read tool")
    elif MUTATION == "remove_clinic_check":
        body = body.replace("Check clinic_id on each returned row", "Ignore clinic_id on each returned row")
    elif MUTATION == "remove_alternative":
        body = body.replace("choose another visible safe read tool", "stop without another read tool")
    elif MUTATION == "report_without_initial_read":
        body = body.replace("use the read route and do not start Report AI", "start Report AI without reading")
    elif MUTATION == "preview_as_facts":
        body = body.replace("they are not live clinic data", "they are live clinic data")
    elif MUTATION == "preset_order":
        body = body.replace("Analytics, Full access", "Full access, Analytics")
    elif MUTATION == "hardcoded_presets":
        body = body.replace("(from the access registry)", "(hardcoded preset names)")
    elif MUTATION == "lose_scope":
        body = body.replace("token with report_ai.write", "token with unknown scope")
    elif MUTATION == "wrong_partial_hint":
        body = body.replace("name that missing tool", "claim report_ai.write is missing")
    elif MUTATION == "remove_instruction_pointer":
        instructions = instructions.replace("welcome_first_session", "")
    elif MUTATION == "frontdesk_advertises_create":
        names.add("create_report_ai_job")
    elif MUTATION == "remove_prompt":
        names.discard("welcome_first_session")
    return body, instructions, names


@pytest.mark.asyncio
async def test_rendered_routes_and_actual_catalogue(monkeypatch):
    async with Client(mcp) as client:
        instructions = client.initialize_result.instructions
        prompts = await client.list_prompts()
        prompt_names = {p.name for p in prompts}
        rendered = await client.get_prompt("welcome_first_session", arguments={})
        assert len(rendered.messages) == 1
        body = rendered.messages[0].content.text
        actual_tools = await client.list_tools()
        frontdesk = {t.name for t in visible_tools_for_scopes(actual_tools, TOKEN_PRESET_SCOPES["frontdesk"])}
        report_ai = {t.name for t in visible_tools_for_scopes(actual_tools, TOKEN_PRESET_SCOPES["report_ai"])}
        body, instructions, prompt_names = _mutate(body, instructions, prompt_names)
        if MUTATION == "frontdesk_advertises_create":
            frontdesk.add("create_report_ai_job")

    assert "welcome_first_session" in prompt_names and "welcome_first_session" in instructions
    assert "tools/list before any write" in instructions
    assert "Do not promise a report to every token" in instructions
    assert "create_report_ai_job" not in frontdesk
    assert {"get_clinics", "get_timesheets"} <= frontdesk
    assert CHAIN <= report_ai
    assert "confirm_report_ai_job_candidate" in report_ai
    assert "only when the catalogue contains" in body
    assert "never try create_report_ai_job to test access" in body
    assert "Read route: choose a safe read tool" in body
    assert "choose another visible safe read tool" in body
    assert "use the read route and do not start Report AI" in body
    assert "Check clinic_id on each returned row" in body
    assert "they are not live clinic data" in body
    assert "token with report_ai.write" in body
    assert "name that missing tool" in body
    assert "(from the access registry)" in body
    labels = get_presets_granting_scope("report_ai.write")
    assert labels == ("Analytics", "Full access")
    assert ", ".join(labels) in body
    assert "Full access, Analytics" not in body
    assert "hardcoded preset names" not in body
    assert "claim report_ai.write is missing" not in body


@pytest.mark.asyncio
async def test_preset_hint_is_rendered_from_registry(monkeypatch):
    monkeypatch.setattr("prompts.get_presets_granting_scope", lambda scope: ("Narrow test label", "Broad test label"))
    async with Client(mcp) as client:
        body = (await client.get_prompt("welcome_first_session", arguments={})).messages[0].content.text
    assert "Narrow test label, Broad test label" in body
    assert "Analytics, Full access" not in body


def test_metric_help_and_save_event_are_distinct():
    from service_metrics import render_prometheus_metrics
    from pathlib import Path
    body = render_prometheus_metrics()
    event_source = (Path(__file__).resolve().parents[1] / "tools" / "report_ai.py").read_text()
    if MUTATION == "change_save_event":
        event_source = event_source.replace('"first_report_saved_at"', '"first_tool_success_at"')
    assert "read-only accounts normally have no save event but remain in the eligible denominator" in body
    assert 'observe_first_action(getattr(credentials, "account_id", None), "first_report_saved_at")' in event_source
