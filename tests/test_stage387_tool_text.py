"""Stage 387: public wording matches the existing tool contracts."""

import ast
from pathlib import Path

import pytest

from prompts import get_report_ai_prompt_helper_text
from server import mcp


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.asyncio
async def test_public_tool_descriptions_route_to_working_tools():
    tools = {tool.name: tool.to_mcp_tool().description for tool in await mcp.list_tools()}
    by_client = tools["get_medical_cards_by_client_id"]
    by_date = tools["get_medical_cards_by_date"]
    debtors = tools["get_debtors"]
    data = tools["get_report_ai_job_data"]

    assert "get_medical_cards_by_date" in by_client
    assert "get_medical_cards" in by_client and "pet_id" in by_client
    assert "general medical-card searches across clients" not in by_client
    assert "get_medical_cards_by_client_id" in by_date
    assert "get_medical_cards" in by_date and "pet_id" in by_date
    assert "broader medical-card search not anchored to a date" not in by_date

    assert "negative client balance" in debtors
    assert "unpaid executed invoices" in debtors
    assert "get_revenue_summary" in debtors
    assert "paid_by_executed_invoices" in debtors
    assert "Report AI" in debtors

    assert "csv_export_url" in data
    assert "relative" in data
    assert "get_report_ai_job_export" in data
    assert "start_report_export" in data
    assert "get_report_export_download" in data
    assert "download_url" in data
    for name in ("get_report_ai_job_data", "start_report_export", "get_report_ai_job_export"):
        assert "CSV/XLSX" not in tools[name]


def test_helper_has_current_observation_and_export_route():
    helper = get_report_ai_prompt_helper_text()
    assert "2026-10-15" in helper
    assert "6–10 секунд" in helper
    for stale in ("от одной до трёх минут", "60–90 секунд", "4 минут 43 секунд"):
        assert stale not in helper
    assert "csv_export_url" in helper and "относительный" in helper
    assert "get_report_ai_job_export" in helper
    assert "start_report_export" in helper
    assert "get_report_export_download" in helper
    assert "download_url" in helper


def test_create_medical_card_docstring_does_not_promise_pet_id_alias():
    tree = ast.parse((ROOT / "tools" / "medical_card.py").read_text(encoding="utf-8"))
    create = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_medical_card"
    )
    assert "patient_id" in [arg.arg for arg in create.args.args]
    assert "pet_id" not in [arg.arg for arg in create.args.args]
    assert "Also accepted as pet_id" not in (ast.get_docstring(create) or "")
