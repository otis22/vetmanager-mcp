"""Rendered MCP first-session contract; STAGE375_MUTATION exercises red guards."""

import os
import re

import pytest
from fastmcp import Client

from server import mcp


MUTATION = os.environ.get("STAGE375_MUTATION", "")


def _mutate_text(body: str) -> str:
    replacements = {
        "remove_catalogue": ("0. Check the available tools/list catalogue first; it is filtered by this token's rights. ", ""),
        "remove_branch_filter": ("filter=[{'property':'clinic_id','operator':'=','value':selected_clinic_id}]", "filter=[]"),
        "create_before_read": ("1. Call get_clinics", "1. Call create_report_ai_job, then get_clinics"),
        "remove_human_check": ("ask the person whether it matches their expectation", "show it without checking"),
        "remove_create_consent": ("Ask explicit consent before calling create_report_ai_job", "Call create_report_ai_job"),
        "remove_save_consent": ("Ask explicit consent to save this specific report", "Save this specific report"),
        "remove_real_rows": ("call get_report_ai_job_data(job_id)", "show the preview"),
        "remove_preview_boundary": ("they are not live clinic data", "they are live clinic data"),
        "guarantee_15_minutes": ("not a 15-minute guarantee", "guaranteed in 15 minutes"),
        "auto_repeat_post": ("Never automatically repeat the create POST", "Automatically repeat the create POST"),
    }
    if MUTATION in replacements:
        old, new = replacements[MUTATION]
        assert old in body, f"mutation target missing: {MUTATION}"
        return body.replace(old, new)
    if MUTATION == "static_pii":
        return body + " Static patient phone: +79991234567."
    return body


@pytest.mark.asyncio
async def test_welcome_prompt_protocol_and_rendered_route():
    async with Client(mcp) as client:
        catalogue = await client.list_prompts()
        if MUTATION == "remove_registration":
            catalogue = [p for p in catalogue if p.name != "welcome_first_session"]
        welcome = [p for p in catalogue if p.name == "welcome_first_session"]
        assert len(welcome) == 1
        prompt = welcome[0]
        arguments = [a.name for a in (prompt.arguments or [])]
        if MUTATION == "required_argument":
            arguments.append("clinic_id")
        if MUTATION == "credential_argument":
            arguments.append("api_key")
        assert arguments == []
        assert prompt.description and len(prompt.description) < 100
        rendered = await client.get_prompt("welcome_first_session", arguments={})
        assert len(rendered.messages) == 1
        message = rendered.messages[0]
        assert message.role == "user"
        body = _mutate_text(message.content.text)
        assert "Credentials are already available from the MCP Bearer token" in body
        assert "Do not ask for a clinic domain or API key" in body
        steps = [body.index(f"{n}. ") for n in range(7)]
        assert steps == sorted(steps)
        for phrase in (
            "tools/list catalogue first", "filtered by this token's rights",
            "If Report AI tools are absent", "stop before create_report_ai_job",
            "1. Call get_clinics", "filter=[{'property':'clinic_id','operator':'=','value':selected_clinic_id}]",
            "Check clinic_id on each returned row", "pagination and partial results",
            "ask the person whether it matches their expectation",
            "Ask explicit consent before calling create_report_ai_job",
            "one useful first report", "same job_id", "bounded waits", "job.next_action",
            "Never automatically repeat the create POST", "mcp_wait_diagnostics",
            "preview_summary and preview_example_row", "they are not live clinic data",
            "mcp_empty_preview_guidance", "Ask explicit consent to save this specific report",
            "meaningful title naming its purpose and period", "save_report_ai_job_as_report",
            "call get_report_ai_job_data(job_id)", "no new report was saved",
            "not a 15-minute guarantee",
        ):
            assert phrase in body, phrase
        assert body.index("get_timesheets(date=today") < body.index("3. Offer one useful")
        assert body.index("ask the person whether it matches") < body.index("3. Offer one useful")
        assert body.index("Ask explicit consent before calling create_report_ai_job") < body.index("4. For the same job_id")
        assert body.index("Ask explicit consent to save this specific report") < body.index("save_report_ai_job_as_report(job_id, title)")
        assert body.index("save_report_ai_job_as_report(job_id, title)") < body.index("call get_report_ai_job_data(job_id)")
        assert "they are live clinic data" not in body
        assert "guaranteed in 15 minutes" not in body
        assert "Automatically repeat the create POST" not in body
        assert not re.search(r"\+7\d{10}|vm_st_[A-Za-z0-9_-]+", body)


@pytest.mark.asyncio
async def test_initialize_points_to_registered_prompt_and_keeps_prior_rules():
    async with Client(mcp) as client:
        instructions = client.initialize_result.instructions
        if MUTATION == "remove_pointer":
            instructions = instructions.replace("welcome_first_session", "")
        if MUTATION == "remove_prior_rules":
            instructions = instructions.replace("Do not paste raw tool response bodies", "")
        names = {p.name for p in await client.list_prompts()}
        if MUTATION == "premature_pointer":
            names.discard("welcome_first_session")
        assert "welcome_first_session" in instructions
        assert "welcome_first_session" in names
        for phrase in (
            "doctors works today", "person's expectation", "clinic's real data",
            "preview", "approve saving", "not verified real data", "report_problem",
            "Do not paste raw tool response bodies", "<client>", "<staff>",
        ):
            assert phrase in instructions
