"""Regression coverage for roadmap stages 244, 245, 247, 248 and 250."""

from __future__ import annotations

import ast
from contextlib import ExitStack
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials
from vm_transport.cache_policy import (
    CACHE_TTL_SHORT_SECONDS, SHORT_TTL_ENTITIES, entity_from_path, ttl_for_entity,
)

DOMAIN = "testclinic"
BASE = "https://testclinic.vetmanager.cloud"
ROOT = Path(__file__).resolve().parents[1]


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _runtime_patch() -> ExitStack:
    headers_patch, runtime_patch = patch_runtime_credentials(
        DOMAIN, "test-key-mock", bearer_token="mock-token", bearer_token_id=1, connection_id=1,
    )
    stack = ExitStack()
    stack.enter_context(headers_patch)
    stack.enter_context(runtime_patch)
    return stack


def _body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@pytest.mark.asyncio
@respx.mock
async def test_update_medical_card_reads_required_context_before_put() -> None:
    _billing_mock()
    get_route = respx.get(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(200, json={"data": {"totalCount": 1, "medicalCards": {
            "id": 42, "patient_id": 7, "doctor_id": 8, "clinic_id": 9,
        }}})
    )
    put_route = respx.put(f"{BASE}/rest/api/MedicalCards/42").mock(
        return_value=httpx.Response(201, json={"data": {"id": 42}})
    )
    with _runtime_patch():
        await mcp.call_tool("update_medical_card", {"card_id": 42, "description": "Updated"})
    assert get_route.call_count == 1
    assert _body(put_route) == {
        "patient_id": 7, "doctor_id": 8, "clinic_id": 9, "description": "Updated",
    }


def test_short_ttl_entities_are_reachable_from_tool_rest_paths() -> None:
    paths = set()
    for source in (ROOT / "tools").glob("*.py"):
        paths.update(re.findall(r'"(/rest/api/[^"/]+)', source.read_text(encoding="utf-8")))
    path_entities = {entity_from_path(path) for path in paths}
    assert SHORT_TTL_ENTITIES <= path_entities
    assert ttl_for_entity(entity_from_path("/rest/api/MedicalCards/6")) == CACHE_TTL_SHORT_SECONDS
    assert ttl_for_entity(entity_from_path("/rest/api/hospital/6")) == CACHE_TTL_SHORT_SECONDS


def _documented_filter_fields(docstring: str) -> set[str] | None:
    match = re.search(r"Allowed properties(?: for both)?: ([a-z0-9_,\s]+)\.", docstring)
    return {field.strip() for field in match.group(1).split(",")} if match else None


def test_documented_list_filter_fields_match_registry_in_both_directions() -> None:
    """Every list tool which opts into the field registry documents its exact set."""
    from filters import FILTER_FIELDS_BY_ENTITY

    for source in (ROOT / "tools").glob("*.py"):
        module = ast.parse(source.read_text(encoding="utf-8"))
        for function in ast.walk(module):
            if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not any(
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "tool"
                for decorator in function.decorator_list
            ):
                continue
            registry_keys = {
                keyword.value.slice.value
                for call in ast.walk(function) if isinstance(call, ast.Call)
                for keyword in call.keywords if keyword.arg == "allowed_filter_properties"
                and isinstance(keyword.value, ast.Subscript)
                and isinstance(keyword.value.value, ast.Name)
                and keyword.value.value.id == "FILTER_FIELDS_BY_ENTITY"
                and isinstance(keyword.value.slice, ast.Constant)
            }
            if not registry_keys:
                continue
            assert len(registry_keys) == 1, f"{source}:{function.name} has ambiguous registry keys"
            documented = _documented_filter_fields(ast.get_docstring(function) or "")
            assert documented is not None, f"{source}:{function.name} lacks Allowed properties"
            assert documented == FILTER_FIELDS_BY_ENTITY[registry_keys.pop()]


@pytest.mark.asyncio
async def test_message_send_descriptions_warn_that_sending_is_irreversible() -> None:
    tools = await mcp.list_tools()
    descriptions = {tool.name: tool.description for tool in tools}
    for name in ("send_message_to_all", "send_message_to_roles", "send_message_to_users"):
        assert "irreversible" in descriptions[name].lower()
        assert "cannot cancel or" in descriptions[name].lower()


@pytest.mark.asyncio
@respx.mock
async def test_invoice_closings_search_both_sides_and_deduplicate() -> None:
    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/closingOfInvoices").mock(
        return_value=httpx.Response(200, json={"data": {"closingOfInvoices": [
            {"id": 1, "minus_document_id": 8, "minus_type_document": "invoice"},
            {"id": 3, "minus_document_id": 8},
        ]}})
    )
    # respx uses routes in registration order; one matcher cannot distinguish filters.
    route.side_effect = [
        httpx.Response(200, json={"data": {"closingOfInvoices": [{"id": 1}, {"id": 3}]}}),
        httpx.Response(200, json={"data": {"closingOfInvoices": [{"id": 2}, {"id": 3}]}}),
    ]
    with _runtime_patch():
        result = await mcp.call_tool("get_closing_of_invoices", {"invoice_id": 8, "limit": 20})
    data = result.structured_content["data"]
    assert [row["id"] for row in data["closingOfInvoices"]] == [1, 3, 2]
    assert data["totalCount"] == 3
