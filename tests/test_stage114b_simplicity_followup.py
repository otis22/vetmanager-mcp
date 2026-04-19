"""Stage 114b regression tests for deferred simplicity follow-up."""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from server import mcp
from tests.runtime_factories import patch_runtime_credentials


REPO_ROOT = Path(__file__).resolve().parent.parent
BASE = "https://testclinic.vetmanager.cloud"
DOMAIN = "testclinic"
API_KEY = "test-key-mock"


def _load_audit_module():
    script_path = REPO_ROOT / "scripts" / "inline_imports_audit.py"
    spec = importlib.util.spec_from_file_location("inline_imports_audit", script_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _function_inline_imports(module_path: Path, function_name: str) -> list[tuple[str, int]]:
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))
    found: list[tuple[str, int]] = []

    def _walk(node: ast.AST, active: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            active = active or node.name == function_name
            for child in node.body:
                _walk(child, active)
            return
        if active and isinstance(node, (ast.Import, ast.ImportFrom)):
            found.append((function_name, node.lineno))
        for child in ast.iter_child_nodes(node):
            _walk(child, active)

    for node in tree.body:
        _walk(node)
    return found


def _billing_mock():
    return respx.get(f"https://billing-api.vetmanager.cloud/host/{DOMAIN}").mock(
        return_value=httpx.Response(200, json={"data": {"url": BASE}})
    )


def _bearer_runtime_patch():
    return patch_runtime_credentials(
        DOMAIN,
        API_KEY,
        bearer_token="mock-token",
        bearer_token_id=1,
        connection_id=1,
    )


def test_inline_import_audit_has_no_undocumented_cases():
    audit = _load_audit_module()
    undocumented = audit.collect_undocumented_inline_imports(REPO_ROOT)
    assert undocumented == []


def test_get_client_profile_has_no_wrapper_hops_left():
    path = REPO_ROOT / "tools" / "client.py"
    source = path.read_text(encoding="utf-8")
    assert "_get_client_profile_impl" not in source
    assert _function_inline_imports(path, "get_client_profile") == []


def test_get_pet_profile_has_no_wrapper_hops_left():
    path = REPO_ROOT / "tools" / "pet.py"
    source = path.read_text(encoding="utf-8")
    assert "_get_pet_profile_impl" not in source
    assert _function_inline_imports(path, "get_pet_profile") == []


def test_profile_resources_no_longer_hand_roll_json_filters():
    client_profile = (REPO_ROOT / "resources" / "client_profile.py").read_text(
        encoding="utf-8"
    )
    pet_profile = (REPO_ROOT / "resources" / "pet_profile.py").read_text(
        encoding="utf-8"
    )
    medical_card = (REPO_ROOT / "tools" / "medical_card.py").read_text(
        encoding="utf-8"
    )

    assert "build_list_query_params(" in client_profile
    assert "json.dumps(" not in client_profile
    assert "build_list_query_params(" in pet_profile
    assert "json.dumps(" not in pet_profile
    assert 'params["filter"] =' not in medical_card


@pytest.mark.asyncio
@respx.mock
async def test_get_medical_cards_by_client_id_preserves_sort_limit_and_offset():
    _billing_mock()
    pet_route = respx.get(f"{BASE}/rest/api/pet").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "pet": [
                        {"id": 1, "alias": "A", "owner_id": 42},
                        {"id": 2, "alias": "B", "owner_id": 42},
                    ]
                }
            },
        )
    )
    medcard_route = respx.get(f"{BASE}/rest/api/MedicalCards").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "data": {"totalCount": 0, "medicalCards": []}},
        )
    )

    headers_patch, runtime_patch = _bearer_runtime_patch()
    with headers_patch, runtime_patch:
        await mcp.call_tool(
            "get_medical_cards_by_client_id",
            {
                "client_id": 42,
                "limit": 7,
                "offset": 3,
                "sort": [{"property": "id", "direction": "DESC"}],
            },
        )

    pet_query = parse_qs(urlparse(str(pet_route.calls.last.request.url)).query)
    assert pet_query["limit"] == ["100"]
    assert pet_query["offset"] == ["0"]

    medcard_query = parse_qs(urlparse(str(medcard_route.calls.last.request.url)).query)
    assert medcard_query["limit"] == ["7"]
    assert medcard_query["offset"] == ["3"]
    assert medcard_query["sort"] == ['[{"property":"id","direction":"DESC"}]']
