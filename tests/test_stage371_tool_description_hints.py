"""Stage 371 guidance must survive the exported MCP tools/list contract."""

import re

import pytest

from filters import FILTER_FIELDS_BY_ENTITY
from server import mcp
from tool_descriptions import RAW_CLAUSE_ENTITIES, RAW_FILTER_FIELD_EXCLUSIONS


async def _exports():
    return {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}


def _assert_invoice(text):
    assert "create_date is a timestamp" in text
    assert "date_from/date_to include full days" in text
    assert "For financial executed invoices, use invoice_date_from/invoice_date_to" in text
    assert "extend date_to" not in text and "add one day" not in text


def _assert_raw_hint(text, clause):
    assert "exact property" in text
    assert "Allowed properties" in text
    assert "error" in text and "retry" in text
    assert "Do not guess" in text
    if clause == "sort":
        assert "direction" in text
    else:
        assert "Do not remove the filter" in text


def _assert_allowed(description, expected):
    match = re.search(r"Allowed properties: ([^.]+)\.", description)
    assert match
    assert set(match.group(1).split(", ")) == expected


def _assert_combination(text):
    assert "combination composition reports" in text
    assert "SQL error" in text
    assert "get_good_combination" in text
    assert "calculate_good_combination_price" in text
    assert "single combination" in text


def _assert_rows(text):
    assert "10000 rows; limited=true means" in text
    assert "Exactly 1000 rows with limited=false is not evidence of truncation" in text
    assert "narrow" in text and "supported export" in text
    assert "save" in text and "confirm" in text
    assert "Exactly 1000 rows is evidence of truncation" not in text


@pytest.mark.asyncio
async def test_invoice_guidance_in_tools_list():
    tool = (await _exports())["get_invoices"]
    _assert_invoice(tool.description)
    _assert_invoice(" ".join(tool.inputSchema["properties"][name].get("description", "")
                            for name in ("date_from", "date_to", "invoice_date_from", "invoice_date_to")))


@pytest.mark.asyncio
async def test_raw_clause_guidance_in_all_tools_list_schemas():
    tools = await _exports()
    for name, entity in RAW_CLAUSE_ENTITIES.items():
        properties = tools[name].inputSchema["properties"]
        assert "exact property" in tools[name].description, name
        for clause in ("filter", "sort"):
            if clause not in properties:
                continue
            description = properties[clause]["description"]
            _assert_raw_hint(description, clause)
            expected = FILTER_FIELDS_BY_ENTITY[entity]
            if clause == "filter":
                expected -= RAW_FILTER_FIELD_EXCLUSIONS.get(name, frozenset())
            _assert_allowed(description, expected)
    assert "document_id" not in tools["get_invoice_documents"].inputSchema["properties"]["filter"]["description"].split("Allowed properties: ", 1)[1].split(".", 1)[0]


@pytest.mark.asyncio
async def test_combination_warning_in_tools_list():
    _assert_combination((await _exports())["create_report_ai_job"].description)


@pytest.mark.asyncio
async def test_row_cap_guidance_in_tools_list():
    _assert_rows((await _exports())["get_report_ai_job_data"].description)


@pytest.mark.asyncio
async def test_guards_fail_when_exported_text_is_broken():
    tools = await _exports()
    invoice = tools["get_invoices"].description
    for broken in (invoice.replace("create_date", "created", 1),
                   invoice.replace("full days", "dates", 1),
                   invoice.replace("invoice_date_from", "other_date", 1),
                   invoice + " extend date_to by one day"):
        with pytest.raises(AssertionError):
            _assert_invoice(broken)
    raw = tools["get_invoices"].inputSchema["properties"]
    for clause in ("filter", "sort"):
        description = raw[clause]["description"]
        with pytest.raises(AssertionError):
            _assert_raw_hint(description.replace("exact property", "similar property", 1), clause)
    with pytest.raises(AssertionError):
        _assert_raw_hint(raw["sort"]["description"].replace("direction", "order"), "sort")
    document_filter = tools["get_invoice_documents"].inputSchema["properties"]["filter"]["description"]
    with pytest.raises(AssertionError):
        _assert_allowed(
            document_filter.replace("Allowed properties: ", "Allowed properties: document_id, ", 1),
            FILTER_FIELDS_BY_ENTITY[RAW_CLAUSE_ENTITIES["get_invoice_documents"]] - {"document_id"},
        )
    combination = tools["create_report_ai_job"].description
    for phrase in ("SQL error", "get_good_combination", "calculate_good_combination_price"):
        with pytest.raises(AssertionError):
            _assert_combination(combination.replace(phrase, "missing", 1))
    rows = tools["get_report_ai_job_data"].description
    for broken in (rows.replace("10000 rows", "1000 rows", 1),
                   rows.replace("limited=true", "limited=false", 1),
                   rows + " Exactly 1000 rows is evidence of truncation."):
        with pytest.raises(AssertionError):
            _assert_rows(broken)
