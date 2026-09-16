"""Stage 328: ``get_properties`` must never disclose clinic secrets."""

from __future__ import annotations

import copy
import ast
from pathlib import Path

import httpx
import pytest
import respx
from fastmcp.exceptions import ToolError

from property_privacy import REDACTED_SECRET, sanitize_properties_response
from server import mcp
from tests.runtime_factories import patch_runtime_credentials


DOMAIN = "testclinic"
API_KEY = "test-key-mock"
BASE = "https://testclinic.vetmanager.cloud"
ROOT = Path(__file__).resolve().parents[1]


def _runtime_patch():
    return patch_runtime_credentials(DOMAIN, API_KEY, bearer_token="mock-token")


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


@pytest.mark.parametrize(
    "row",
    [
        {"property_name": "rest_api_key", "property_value": "short"},
        {"property_name": "futureAuthKey", "property_value": "short"},
        {"property_title": "Пароль SMS-центра", "property_value": "short"},
        {"property_title": "Ключ API", "property_value": None},
        {"property_name": "rest_api_key", "property_value": 7},
    ],
)
def test_secret_property_name_or_title_is_always_replaced(row):
    result = sanitize_properties_response({"data": {"properties": [row]}})
    assert result["data"]["properties"][0]["property_value"] == REDACTED_SECRET


@pytest.mark.parametrize(
    "secret_value",
    [
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signaturevalue123",
        "sk-ExampleSecretToken1234567890",
        "xoxb-ExampleSecretToken1234567890",
        "AKIAIOSFODNN7EXAMPLE",
        "https://example.test/hook?api_key=ExampleSecretToken1234567890",
        "admin:s3cret-password",
        "AbCdEfGhIjKlMnOpQrStUvWx1234",
        "0123456789abcdef0123456789abcdef",
        "QWJjZEVmR2hJaktMbU5vUHFSU3RVdld4",
    ],
)
def test_secret_shaped_value_is_replaced_even_with_safe_name(secret_value):
    result = sanitize_properties_response({"data": {"properties": [{
        "property_name": "ordinary_setting", "property_value": secret_value,
    }]}})
    assert result["data"]["properties"][0]["property_value"] == REDACTED_SECRET


@pytest.mark.parametrize(
    "ordinary_value",
    ["1", "true", "ru", "Europe/Moscow", "operator@example.test", "+79990000000",
     '{"timezone":"Europe/Moscow","enabled":true}', "550e8400-e29b-41d4-a716-446655440000",
     "Mon:Fri", "smtp:tls", "/api/v1/clinic/settings/export"],
)
def test_ordinary_values_are_not_replaced(ordinary_value):
    result = sanitize_properties_response({"data": {"properties": [{
        "property_name": "ordinary_setting", "property_value": ordinary_value,
    }]}})
    assert result["data"]["properties"][0]["property_value"] == ordinary_value


def test_sanitizer_preserves_pagination_and_does_not_mutate_upstream_response():
    upstream = {"success": True, "data": {"totalCount": 2, "properties": [
        {"id": 1, "property_name": "timezone", "property_value": "Europe/Moscow"},
        {"id": 2, "property_name": "rest_api_key", "property_value": "short"},
    ]}}
    before = copy.deepcopy(upstream)

    result = sanitize_properties_response(upstream)

    assert result["data"]["totalCount"] == 2
    assert len(result["data"]["properties"]) == 2
    assert result["data"]["properties"][1]["property_value"] == REDACTED_SECRET
    assert upstream == before


@pytest.mark.asyncio
@respx.mock
async def test_get_properties_redacts_before_mcp_returns_the_page():
    _billing_mock()
    respx.get(f"{BASE}/rest/api/properties").mock(return_value=httpx.Response(200, json={
        "success": True, "data": {"totalCount": 2, "properties": [
            {"id": 1, "property_name": "timezone", "property_value": "Europe/Moscow"},
            {"id": 2, "property_name": "rest_api_key", "property_value": "short"},
        ]},
    }))
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        result = await mcp.call_tool("get_properties", {"limit": 2, "offset": 0})

    payload = result.structured_content
    assert payload["data"]["totalCount"] == 2
    assert payload["data"]["properties"][1]["property_value"] == REDACTED_SECRET


@pytest.mark.asyncio
@pytest.mark.parametrize("argument", ["filter", "sort"])
@respx.mock
async def test_property_value_filter_and_sort_are_rejected_before_http(argument):
    _billing_mock()
    route = respx.get(f"{BASE}/rest/api/properties").mock(
        return_value=httpx.Response(200, json={"success": True, "data": {"properties": []}})
    )
    args = {argument: [{"property": "property_value", "operator": "LIKE", "value": "x"}]}
    if argument == "sort":
        args = {"sort": [{"property": "property_value", "direction": "ASC"}]}
    headers_patch, runtime_patch = _runtime_patch()
    with headers_patch, runtime_patch:
        with pytest.raises(ToolError, match="property_value"):
            await mcp.call_tool("get_properties", args)

    assert not route.called


def test_every_properties_tool_path_has_the_subject_sanitizer_guard():
    """A future /properties route must not silently bypass the local helper."""
    offenders = []
    for directory in (ROOT / "tools", ROOT / "resources"):
        for source in directory.glob("*.py"):
            tree = ast.parse(source.read_text(encoding="utf-8"))
            for function in ast.walk(tree):
                if not isinstance(function, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = [node for node in ast.walk(function) if isinstance(node, ast.Call)]
                reads_properties = any(
                    any(isinstance(arg, ast.Constant) and arg.value == "/rest/api/properties"
                        for arg in call.args)
                    for call in calls
                )
                has_sanitizer = any(
                    isinstance(call.func, ast.Name)
                    and call.func.id == "sanitize_properties_response"
                    for call in calls
                )
                if reads_properties and not has_sanitizer:
                    offenders.append(f"{source.name}:{function.name}")
    assert not offenders
