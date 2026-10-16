"""Stage 395: one public identifier vocabulary across the MCP boundary."""

import ast
import json
import re
from pathlib import Path

import httpx
import pytest
import respx

from server import mcp
from identifier_aliases import normalize_arguments, normalize_result
from tests.runtime_factories import patch_runtime_credentials


ROOT = Path(__file__).resolve().parents[1]
ALIASES = {"patient_id": "pet_id", "owner_id": "client_id", "user_id": "doctor_id"}


@pytest.mark.parametrize("entity_tool,canonical,api_name", [
    ("get_pets", "client_id", "owner_id"),
    ("get_medical_cards", "pet_id", "patient_id"),
    ("get_admissions", "doctor_id", "user_id"),
])
def test_filter_and_sort_translate_at_vm_boundary(entity_tool, canonical, api_name):
    arguments = {"filter": [{"property": canonical, "operator": "=", "value": 7}],
                 "sort": [{"property": canonical, "direction": "ASC"}]}
    result = normalize_arguments(arguments, tool_name=entity_tool)
    assert result["filter"][0]["property"] == api_name
    assert result["sort"][0]["property"] == api_name
    assert arguments["filter"][0]["property"] == canonical


def test_aliases_and_canonical_values_conflict_closed():
    from fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match="client_id"):
        normalize_arguments({"owner_id": 7, "client_id": 8}, tool_name="get_pets")
    assert normalize_arguments({"owner_id": 7, "client_id": 7}, tool_name="get_pets") == {"client_id": 7}
    with pytest.raises(ToolError, match="client_id"):
        normalize_arguments({"filter": [
            {"property": "owner_id", "operator": "=", "value": 7},
            {"property": "client_id", "operator": "=", "value": 8},
        ]}, tool_name="get_pets")
    with pytest.raises(ToolError, match="client_id"):
        normalize_arguments({"filter": [
            {"property": "owner_id", "operator": "=", "value": 7},
            {"property": "owner_id", "operator": "=", "value": 8},
            {"property": "client_id", "operator": "=", "value": 8},
        ]}, tool_name="get_pets")
    with pytest.raises(ToolError, match="client_id"):
        normalize_arguments({"sort": [
            {"property": "owner_id", "direction": "ASC"},
            {"property": "client_id", "direction": "DESC"},
        ]}, tool_name="get_pets")


def test_nested_result_matrix_and_conflict():
    value = {"data": [{"patient_id": 1, "owner_id": 2, "nested": {"user_id": 3}}]}
    assert normalize_result(value) == {"data": [{"pet_id": 1, "client_id": 2, "nested": {"doctor_id": 3}}]}
    conflict = normalize_result({"patient_id": 1, "pet_id": 2})
    assert conflict == {"pet_id": 2, "_mcp_identifier_conflicts": [
        {"field": "pet_id", "values": [2, 1]}
    ]}


def test_report_column_names_are_not_identifier_fields():
    report = {"data": {"rows": [{"patient_id": 1, "owner_id": 2, "user_id": 3}],
                       "columns": ["patient_id", "owner_id", "user_id"],
                       "recognized": {"preview_example_row": {"patient_id": 9}},
                       "metadata": {"patient_id": 1}}}
    result = normalize_result(report, report_mode=True)
    assert result["data"]["rows"] == report["data"]["rows"]
    assert result["data"]["columns"] == report["data"]["columns"]
    assert result["data"]["recognized"]["preview_example_row"] == {"patient_id": 9}
    assert result["data"]["metadata"] == {"pet_id": 1}


def test_every_report_ai_result_uses_column_preserving_path():
    from tools import REPORT_COLUMN_TOOLS

    tree = ast.parse((ROOT / "tools" / "report_ai.py").read_text())
    registered = {node.name for node in ast.walk(tree)
                  if isinstance(node, ast.AsyncFunctionDef)
                  and any(isinstance(decorator, ast.Attribute) and decorator.attr == "tool"
                          for decorator in node.decorator_list)}
    assert registered - {"get_report_ai_prompt_helper", "rate_report_ai_job"} == REPORT_COLUMN_TOOLS


@pytest.mark.asyncio
async def test_registered_report_tool_keeps_generated_column_names(monkeypatch):
    import tools.report_ai as report_module

    async def fake_call(*args, **kwargs):
        return {"success": True, "data": {"rows": [{"patient_id": 1}],
                                          "columns": ["patient_id"],
                                          "metadata": {"owner_id": 2}}}

    monkeypatch.setattr(report_module, "_call_vm", fake_call)
    monkeypatch.setattr(report_module, "_annotate_report_ai_data_payload", lambda payload: payload)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock",
                                                 bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        result = await mcp.call_tool("get_report_ai_job_data", {"job_id": 1})
    data = result.structured_content["data"]
    assert data["rows"] == [{"patient_id": 1}]
    assert data["columns"] == ["patient_id"]
    assert data["metadata"] == {"client_id": 2}


@pytest.mark.asyncio
async def test_reject_report_candidate_keeps_preview_column_names(monkeypatch):
    import tools.report_ai as report_module

    async def fake_call(*args, **kwargs):
        return {"success": True, "data": {"job": {"id": 1, "status": "building_preview",
                "recognized": {"preview_example_row": {"patient_id": 3}},
                "owner_id": 2}}}

    monkeypatch.setattr(report_module, "_call_vm", fake_call)
    monkeypatch.setattr(report_module, "_best_effort_observation", lambda *args, **kwargs: None)
    monkeypatch.setattr(report_module, "_remember_reject_pending", lambda *args, **kwargs: None)
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock",
                                                 bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        result = await mcp.call_tool("reject_report_ai_job_candidate", {"job_id": 1})
    job = result.structured_content["data"]["job"]
    assert job["recognized"]["preview_example_row"] == {"patient_id": 3}
    assert job["client_id"] == 2


def test_all_tool_registrations_use_the_common_proxy():
    entry = ast.parse((ROOT / "tools" / "__init__.py").read_text())
    register = next(n for n in entry.body if isinstance(n, ast.FunctionDef) and n.name == "register_all")
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_ToolRegistrationProxy" for n in ast.walk(register))
    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "canonical_tool" for n in ast.walk(entry))
    proxy = next(n for n in entry.body if isinstance(n, ast.ClassDef) and n.name == "_ToolRegistrationProxy")
    proxy_tool = next(n for n in proxy.body if isinstance(n, ast.FunctionDef) and n.name == "tool")
    authorized = {id(n) for n in ast.walk(proxy_tool) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "tool"
                  and isinstance(n.func.value, ast.Attribute) and n.func.value.attr == "_mcp"
                  and n.args and isinstance(n.args[0], ast.Call)
                  and isinstance(n.args[0].func, ast.Name) and n.args[0].func.id == "canonical_tool"}
    assert len(authorized) == 2
    registrations = [n for n in ast.walk(register) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Name) and n.func.id.startswith("register_")]
    assert registrations
    assert all(len(n.args) == 1 and isinstance(n.args[0], ast.Name)
               and n.args[0].id == "tool_mcp" for n in registrations)
    for source in (ROOT / "tools").glob("*.py"):
        if source.name == "__init__.py":
            continue
        tree = ast.parse(source.read_text())
        decorators = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                      and any(isinstance(d, ast.Attribute) and d.attr == "tool" for d in n.decorator_list)]
        assert decorators == [n for parent in ast.walk(tree) if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and parent.name == "register" for n in ast.walk(parent)
                              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                              and any(isinstance(d, ast.Attribute) and d.attr == "tool" for d in n.decorator_list)], source
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "register":
                assert node.args.args[0].arg == "mcp", source
                for nested in ast.walk(node):
                    if isinstance(nested, ast.Call) and isinstance(nested.func, ast.Attribute) and nested.func.attr in {"tool", "add_tool"}:
                        assert nested.func.attr == "tool" and isinstance(nested.func.value, ast.Name) and nested.func.value.id == "mcp", source
    for source in ROOT.rglob("*.py"):
        if set(source.relative_to(ROOT).parts) & {"tests", "scripts", ".venv", "__pycache__"}:
            continue
        tree = entry if source == ROOT / "tools" / "__init__.py" else ast.parse(source.read_text())
        assert not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and n.func.attr in {"tool", "add_tool"} and id(n) not in authorized
                       for n in ast.walk(tree)), source
        if source.name == "server.py":
            registrations = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                             and isinstance(n.func, ast.Name) and n.func.id.startswith("register_")
                             and n.args and isinstance(n.args[0], ast.Name) and n.args[0].id == "mcp"]
            assert {n.func.id for n in registrations} == {
                "register_all", "register_prompts", "register_web_routes"
            }


@pytest.mark.asyncio
async def test_catalogue_has_only_canonical_identifiers():
    for tool in await mcp.list_tools():
        exposed = tool.to_mcp_tool()
        schema = exposed.inputSchema
        assert not (set(schema.get("properties", {})) & set(ALIASES)), tool.name
        for old in ALIASES:
            assert not re.search(rf"\b{old}\b", exposed.description), tool.name
            assert all(not re.search(rf"\b{old}\b", str(field.get("description", "")))
                       for field in schema.get("properties", {}).values()), tool.name


@pytest.mark.asyncio
async def test_descriptions_do_not_explain_an_identity_mapping():
    exports = {tool.name: tool.to_mcp_tool() for tool in await mcp.list_tools()}
    admission = exports["get_admissions"].inputSchema["properties"]
    assert "internally mapped" not in admission["doctor_id"]["description"]
    assert "internally mapped" not in admission["pet_id"]["description"]
    pet = exports["get_pets"].inputSchema["properties"]
    assert "not client_id" not in pet["client_id"]["description"]


@pytest.mark.asyncio
@respx.mock
async def test_pet_read_accepts_canonical_and_alias_and_normalizes_nested_response():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(return_value=httpx.Response(200, json={"data": {"url": base}}))
    route = respx.get(f"{base}/rest/api/pet").mock(return_value=httpx.Response(200, json={"data": {"totalCount": 1, "pet": [{"id": 7, "owner_id": 5, "nested": {"patient_id": 7, "user_id": 3}}]}}))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        for name in ("client_id", "owner_id"):
            result = await mcp.call_tool("get_pets", {name: 5})
            assert result.structured_content["data"]["pet"][0]["client_id"] == 5
    assert route.call_count >= 1


@pytest.mark.asyncio
@respx.mock
async def test_registered_filter_and_sort_use_vm_property_names():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(return_value=httpx.Response(200, json={"data": {"url": base}}))
    route = respx.get(f"{base}/rest/api/pet").mock(return_value=httpx.Response(200, json={"data": {"totalCount": 0, "pet": []}}))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        await mcp.call_tool("get_pets", {
            "filter": [{"property": "client_id", "operator": "=", "value": 5}],
            "sort": [{"property": "client_id", "direction": "ASC"}],
        })
    query = route.calls.last.request.url.params
    assert json.loads(query["filter"])[0]["property"] == "owner_id"
    assert json.loads(query["sort"])[0]["property"] == "owner_id"


@pytest.mark.asyncio
@respx.mock
async def test_create_medical_card_maps_pet_id_to_vm_patient_id():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(return_value=httpx.Response(200, json={"data": {"url": base}}))
    route = respx.post(f"{base}/rest/api/MedicalCards").mock(return_value=httpx.Response(201, json={"data": {"id": 11}}))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        for field in ("pet_id", "patient_id"):
            result = await mcp.call_tool("create_medical_card", {field: 7, "doctor_id": 3, "clinic_id": 1, "date_create": "2026-10-15"})
            assert not result.is_error
    assert route.call_count == 2
    assert json.loads(route.calls.last.request.content)["patient_id"] == 7


@pytest.mark.asyncio
@respx.mock
async def test_successful_write_with_conflicting_response_ids_stays_successful():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(return_value=httpx.Response(200, json={"data": {"url": base}}))
    respx.post(f"{base}/rest/api/MedicalCards").mock(return_value=httpx.Response(201, json={
        "success": True, "data": {"patient_id": 7, "pet_id": 8, "id": 11}
    }))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        result = await mcp.call_tool("create_medical_card", {
            "pet_id": 7, "doctor_id": 3, "clinic_id": 1, "date_create": "2026-10-15"
        })
    assert not result.is_error
    assert result.structured_content["data"]["id"] == 11
    assert result.structured_content["data"]["_mcp_identifier_conflicts"] == [
        {"field": "pet_id", "values": [8, 7]}
    ]


@pytest.mark.asyncio
@respx.mock
async def test_user_id_and_doctor_id_address_same_staff_tool():
    base = "https://testclinic.vetmanager.cloud"
    respx.get("https://billing-api.vetmanager.cloud/host/testclinic").mock(return_value=httpx.Response(200, json={"data": {"url": base}}))
    respx.get(f"{base}/rest/api/user/3").mock(return_value=httpx.Response(200, json={"data": {"user": {"id": 3}}}))
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock", bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        for field in ("doctor_id", "user_id"):
            result = await mcp.call_tool("get_user_by_id", {field: 3})
            assert result.structured_content["data"]["user"]["id"] == 3


@pytest.mark.asyncio
async def test_local_validation_error_names_client_id():
    headers, runtime = patch_runtime_credentials("testclinic", "test-key-mock",
                                                 bearer_token="mock", bearer_token_id=1, connection_id=1)
    with headers, runtime:
        with pytest.raises(Exception) as exc:
            await mcp.call_tool("get_pets", {"alias": "Rex"})
    assert "client_id" in str(exc.value)
    assert "owner_id" not in str(exc.value)
