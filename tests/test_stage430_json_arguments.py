"""Stage 430: JSON encoded structured MCP arguments reach handlers."""

import json
import ast
from pathlib import Path
from typing import Annotated, get_args, get_origin

import pytest
from fastmcp import FastMCP
from exceptions import ToolInputError
from pydantic import BeforeValidator

from tools import client, reference


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module", "name", "property_name"),
    [(client, "get_clients", "id"), (reference, "get_breeds", "title")],
)
async def test_json_filter_reaches_handler(monkeypatch, module, name, property_name):
    seen = []

    async def fake_crud_list(*args, **kwargs):
        seen.append(kwargs)
        return {"data": {"items": []}}

    monkeypatch.setattr(module, "crud_list", fake_crud_list)
    mcp = FastMCP("stage430")
    module.register(mcp)
    clause = {"property": property_name, "value": 1, "operator": "="}
    result = await mcp.call_tool(name, {"filter": json.dumps([clause])})
    assert not result.is_error
    assert seen
    assert seen[0]["filters"][0] == clause


@pytest.mark.asyncio
async def test_json_filter_edges(monkeypatch):
    seen = []

    async def fake_crud_list(*args, **kwargs):
        seen.append(kwargs)
        return {"data": {"items": []}}

    monkeypatch.setattr(reference, "crud_list", fake_crud_list)
    mcp = FastMCP("stage430-edges")
    reference.register(mcp)
    for value, expected in [("[]", None), ("null", None), ([], None), (None, None)]:
        await mcp.call_tool("get_breeds", {"filter": value})
        assert seen[-1]["filters"] == expected
    for value in ("", "{broken", '{}', '"text"'):
        with pytest.raises(ToolInputError, match="expected a JSON array"):
            await mcp.call_tool("get_breeds", {"filter": value})


def _bare_structural_argument(source: str) -> list[str]:
    violations = []
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not any(isinstance(d, ast.Attribute) and d.attr == "tool" for d in node.decorator_list):
            continue
        for arg in node.args.args + node.args.kwonlyargs:
            if arg.annotation is None:
                continue
            for part in ast.walk(arg.annotation):
                if isinstance(part, ast.Subscript) and isinstance(part.value, ast.Name) and part.value.id in {"list", "dict"}:
                    violations.append(f"{node.name}.{arg.arg}")
                    break
    return violations


def test_all_mcp_structural_arguments_use_shared_alias():
    violations = []
    for path in Path("tools").glob("*.py"):
        violations.extend(f"{path}:{x}" for x in _bare_structural_argument(path.read_text()))
    assert not violations


def test_inventory_guard_detects_bare_optional_list():
    source = "@mcp.tool\ndef example(items: list[int] | None = None):\n    pass\n"
    assert _bare_structural_argument(source) == ["example.items"]


def _contains_structure(annotation):
    return get_origin(annotation) in {list, dict} or any(
        _contains_structure(arg) for arg in get_args(annotation) if not isinstance(arg, BeforeValidator)
    )


def _contains_parser(annotation):
    if get_origin(annotation) is Annotated and any(
        isinstance(arg, BeforeValidator) for arg in get_args(annotation)[1:]
    ):
        return True
    return any(_contains_parser(arg) for arg in get_args(annotation) if not isinstance(arg, BeforeValidator))


@pytest.mark.asyncio
async def test_registered_tool_structural_arguments_have_validator():
    from server import mcp

    violations = []
    for tool in await mcp.list_tools():
        for name, annotation in tool.fn.__annotations__.items():
            if name != "return" and _contains_structure(annotation) and not _contains_parser(annotation):
                violations.append(f"{tool.name}.{name}")
    assert not violations
