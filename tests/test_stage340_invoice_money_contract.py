"""Stage 340: published invoice money contract and scoped feedback guidance."""

import json
from pathlib import Path

import pytest

from agent_feedback_service import FeedbackIncident, match_rules
from scripts.seed_known_issues import SEED_ISSUES, validate_seed_definitions
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


ROOT = Path(__file__).resolve().parents[1]
FORMULA = "default_price - price*((100-discount)/100)*((100+increase)/100)"


@pytest.mark.asyncio
async def test_published_invoice_tool_descriptions_name_units_and_write_caveat():
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    for name in ("get_invoices", "update_invoice"):
        description = tools[name].description
        for field in ("discount", "increase", "percent", "amount"):
            assert field in description, (name, field)
        assert "percentage" in description.lower(), name
        assert "rouble" in description.lower(), name
    assert FORMULA in tools["get_invoices"].description
    assert "does not recalculate amount" in tools["update_invoice"].description


@pytest.mark.asyncio
async def test_report_ai_helper_explains_discount_formula_and_not_sum_field():
    headers_patch, runtime_patch = patch_runtime_credentials("testclinic", "test-key-mock")
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_report_ai_prompt_helper", {})
    body = result.structured_content["helper_text"]
    assert FORMULA in body
    assert "invoice.discount" in body
    assert "не суммируйте" in body


def test_entity_reference_describes_all_six_money_fields():
    body = (ROOT / "artifacts/api_entity_reference-ru.md").read_text(encoding="utf-8")
    invoice = body.split("### 2.19. Invoice", 1)[1].split("### 2.21.", 1)[0]
    rows = {field: next(line for line in invoice.splitlines() if line.startswith(f"| `{field}` |")) for field in ("discount", "increase", "percent", "amount", "price", "default_price")}
    assert "процент скидки" in rows["discount"].lower()
    assert "процент наценки" in rows["increase"].lower()
    assert "после скидки и наценки" in rows["amount"].lower()
    assert "не эффективная" in rows["percent"].lower()
    assert "без скидки" in rows["percent"].lower()
    assert "сумма позиции" in rows["price"].lower()
    assert "сумма позиции" in rows["default_price"].lower()


def test_seed_invoice_discount_issue_matches_only_relevant_tools_and_text():
    validate_seed_definitions()
    issue = next(item for item in SEED_ISSUES if item.slug == "invoice-discount-is-percent")
    assert issue.related_tool is None
    assert FORMULA in " ".join(issue.agent_playbook["steps"])
    assert "не сумм" in " ".join(issue.agent_playbook["do_not_do"]).lower()
    rules = json.dumps(issue.match_rules)
    for tool in ("get_invoices", "get_report_ai_prompt_helper"):
        assert match_rules(rules, FeedbackIncident(related_tool=tool, error_excerpt="invoice.discount сумма скидки в рублях"))
    for tool in ("create_report_ai_job", "get_report_ai_job_data", "get_invoices"):
        assert not match_rules(rules, FeedbackIncident(related_tool=tool, error_excerpt="unrelated failure"))
    for tool in ("create_report_ai_job", "get_report_ai_job_data"):
        assert not match_rules(rules, FeedbackIncident(related_tool=tool, error_excerpt="invoice.discount сумма скидки в рублях"))
