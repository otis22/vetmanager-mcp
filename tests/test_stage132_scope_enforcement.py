"""Stage 132 runtime tool-level scope preflight coverage."""

from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

import tools
from tests.runtime_factories import make_runtime_credentials
from token_scopes import SCOPE_ADMISSIONS_READ, SCOPE_CLIENTS_READ, SCOPE_PETS_READ
from token_scopes import SCOPE_FINANCE_READ


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
    message = str(exc_info.value)
    assert "Tool 'get_inactive_pets' is not permitted for this token." in message
    assert "Missing scopes: finance.read, medical_cards.read" in message
    assert "Current preset: custom scopes" in message
    assert "Allowed presets: Full access, Read only" in message
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
async def test_tool_preflight_denial_message_infers_current_preset(monkeypatch):
    called = False
    credentials = make_runtime_credentials(
        "clinic",
        "key",
        scopes=(SCOPE_CLIENTS_READ, SCOPE_FINANCE_READ),
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
    message = str(exc_info.value)
    assert "Current preset: custom scopes" in message
    assert "Required scopes: clients.read, finance.read, medical_cards.read, pets.read" in message
    assert "Missing scopes: medical_cards.read, pets.read" in message
    assert "vm_st_" not in message
    assert "clinic" not in message


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
