"""Stage 132 runtime tool-level scope preflight coverage."""

from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

import tools
from tests.runtime_factories import make_runtime_credentials
from token_scopes import SCOPE_ADMISSIONS_READ, SCOPE_CLIENTS_READ, SCOPE_PETS_READ


@pytest.mark.asyncio
async def test_tool_preflight_denies_missing_scope_before_body(monkeypatch):
    called = False
    credentials = make_runtime_credentials(
        "clinic",
        "key",
        scopes=(SCOPE_CLIENTS_READ,),
    )
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def tool_func():
        nonlocal called
        called = True
        return {"ok": True}

    wrapped = tools._wrap_tool_with_depersonalization(
        tool_func,
        tool_name="get_inactive_pets",
    )

    with pytest.raises(ToolError) as exc_info:
        await wrapped()

    assert called is False
    assert str(exc_info.value) == "Tool is not permitted for this token."
    assert exc_info.value.__cause__ is None


@pytest.mark.asyncio
async def test_tool_preflight_fails_closed_for_unknown_tool_mapping(monkeypatch):
    called = False
    credentials = make_runtime_credentials(
        "clinic",
        "key",
        scopes=(SCOPE_CLIENTS_READ,),
    )
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def tool_func():
        nonlocal called
        called = True
        return {"ok": True}

    wrapped = tools._wrap_tool_with_depersonalization(
        tool_func,
        tool_name="unmapped_tool",
    )

    with pytest.raises(ToolError, match="Tool is not permitted for this token."):
        await wrapped()

    assert called is False


@pytest.mark.asyncio
async def test_tool_preflight_fails_closed_for_empty_scopes(monkeypatch):
    called = False
    credentials = make_runtime_credentials("clinic", "key", scopes=())
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def tool_func():
        nonlocal called
        called = True
        return {"ok": True}

    wrapped = tools._wrap_tool_with_depersonalization(
        tool_func,
        tool_name="get_clients",
    )

    with pytest.raises(ToolError, match="Tool is not permitted for this token."):
        await wrapped()

    assert called is False


@pytest.mark.asyncio
async def test_aggregate_tool_missing_scope_makes_zero_body_calls(monkeypatch):
    called = False
    credentials = make_runtime_credentials(
        "clinic",
        "key",
        scopes=(SCOPE_PETS_READ, SCOPE_ADMISSIONS_READ),
    )
    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    async def tool_func():
        nonlocal called
        called = True
        return {"partial": "would call upstream"}

    wrapped = tools._wrap_tool_with_depersonalization(
        tool_func,
        tool_name="get_doctor_free_slots",
    )

    with pytest.raises(ToolError, match="Tool is not permitted for this token."):
        await wrapped()

    assert called is False
