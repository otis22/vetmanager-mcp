"""The actual tools/list export must teach callers the accepted raw clauses."""

import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ToolError

from filters import FILTER_FIELDS_BY_ENTITY, SortPropertyValidationError, validate_sort_properties
from server import mcp
from structured_logging import JsonLogFormatter
from tests.runtime_factories import patch_runtime_credentials


def test_sqlalchemy_stays_on_2_0_line_in_both_dependency_sources():
    """Production and test installs must not silently resolve to SQLAlchemy 2.1."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = root / "Dockerfile"
    production_dependencies = dockerfile.read_text().split("FROM base AS production", 1)[0]
    assert '"sqlalchemy[asyncio]>=2.0.0,<2.1"' in production_dependencies
    assert '"sqlalchemy[asyncio]>=2.0.0,<2.1"' in (root / "pyproject.toml").read_text()


@pytest.mark.asyncio
async def test_all_advertised_raw_clauses_name_fields_and_format():
    from tool_descriptions import RAW_CLAUSE_ENTITIES, RAW_FILTER_FIELD_EXCLUSIONS

    exports = {tool.name: tool.to_mcp_tool().inputSchema["properties"] for tool in await mcp.list_tools()}
    actual = {name for name, props in exports.items() if {"sort", "filter"} & props.keys()}
    assert actual == set(RAW_CLAUSE_ENTITIES)
    for name in actual:
        entity = RAW_CLAUSE_ENTITIES[name]
        fields = FILTER_FIELDS_BY_ENTITY[entity]
        for clause in ("sort", "filter"):
            if clause not in exports[name]:
                continue
            description = exports[name][clause].get("description", "")
            assert "property" in description and ("direction" if clause == "sort" else "operator") in description, (name, clause)
            match = re.search(r"Allowed properties: ([^.]+)\.", description)
            assert match, (name, clause)
            advertised = set(match.group(1).split(", "))
            expected = fields - RAW_FILTER_FIELD_EXCLUSIONS.get(name, frozenset()) if clause == "filter" else fields
            assert expected == advertised, (name, clause, sorted(expected ^ advertised))
            if name == "get_invoice_documents" and clause == "filter":
                assert "document_id" not in advertised


@pytest.mark.asyncio
async def test_party_lookup_is_discoverable_and_ignored_clauses_are_gone():
    tools = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    exports = {name: tool.inputSchema["properties"] for name, tool in tools.items()}
    for name in ("get_diagnoses", "get_anonymous_clients", "get_message_reports"):
        assert "sort" not in exports[name] and "filter" not in exports[name]
    assert "good_id" in exports["get_party_account_docs"]["filter"]["description"]
    assert "document_id" in exports["get_party_account_docs"]["filter"]["description"]
    assert "good_id" not in exports["get_party_accounts"]["filter"]["description"]
    assert "get_party_account_by_id" in tools["get_party_account_docs"].description
    assert "begin_datetime" in exports["get_timesheets"]["sort"]["description"]
    assert "hospital_block_id" in exports["get_hospitalizations"]["sort"]["description"]
    assert "invoice_date" in exports["get_invoices"]["sort"]["description"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["get_diagnoses", "get_anonymous_clients", "get_message_reports"])
async def test_removed_noop_clauses_fail_explicitly(name):
    from fastmcp.exceptions import ValidationError

    with pytest.raises(ValidationError, match="Unexpected keyword argument"):
        await mcp.call_tool(name, {"sort": [{"property": "id", "direction": "ASC"}]})


@pytest.mark.asyncio
async def test_catalog_guard_has_red_mutations():
    component = next(
        c for c in mcp._local_provider._components.values()
        if getattr(c, "name", None) == "get_timesheets"
    )
    schema = component.parameters["properties"]["sort"]
    original = schema["description"]
    try:
        schema["description"] = ""
        with pytest.raises(AssertionError):
            await test_all_advertised_raw_clauses_name_fields_and_format()
        schema["description"] = original.replace("shedule_id", "")
        with pytest.raises(AssertionError):
            await test_all_advertised_raw_clauses_name_fields_and_format()
    finally:
        schema["description"] = original


def test_sort_rejection_logs_only_safe_field_name(caplog):
    allowed = frozenset({"id"})
    with caplog.at_level(logging.WARNING):
        with pytest.raises(SortPropertyValidationError):
            validate_sort_properties([{"property": "wrong_field", "direction": "ASC"}], allowed)
    assert any(getattr(record, "sort_property", None) == "wrong_field" for record in caplog.records)
    assert any('"sort_property": "wrong_field"' in JsonLogFormatter().format(record) for record in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(SortPropertyValidationError) as rejected:
            validate_sort_properties([{"property": "person@example.com\nsecret", "direction": "ASC"}], allowed)
    assert any(getattr(record, "sort_property", None) == "<invalid_identifier>" for record in caplog.records)
    assert all("person@example.com" not in record.getMessage() for record in caplog.records)
    assert "person@example.com" not in str(rejected.value)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "required"),
    [
        ("get_medical_cards", {"pet_id": 1}),
        ("get_medical_cards_by_date", {"date": "2026-09-25"}),
        ("get_medical_cards_by_client_id", {"client_id": 1}),
        ("get_invoice_documents", {"invoice_id": 1}),
    ],
)
async def test_newly_mapped_routes_reject_unknown_sort_before_http(name, required):
    args = {**required, "sort": [{"property": "invalid_stage348_field", "direction": "ASC"}]}
    headers_patch, runtime_patch = patch_runtime_credentials("devtr6", "unused-test-key")
    with headers_patch, runtime_patch, patch("vetmanager_client.VetmanagerClient.get", new_callable=AsyncMock) as get:
        with pytest.raises(ToolError, match="invalid_stage348_field"):
            await mcp.call_tool(name, args)
    get.assert_not_called()
