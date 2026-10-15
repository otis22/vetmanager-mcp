"""Stage 397: the agent sees only its effective access and MCP limits."""

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from access_summary import summarize_access
from exceptions import AuthError
from tool_access_registry import (
    BASELINE_ALLOWED_TOOLS,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
    TOKEN_PRESET_LABELS,
)
from tool_scope_security import ScopeDeniedToolError, visible_tools_for_scopes
from auth import rate_limit


@pytest.mark.parametrize("preset", ["read_only", "frontdesk", "full_access"])
def test_whoami_contract_matches_effective_scopes(preset, monkeypatch):
    from tools.whoami import build_whoami

    monkeypatch.setenv("BEARER_RATE_LIMIT_REQUESTS", "317")
    monkeypatch.setenv("BEARER_RATE_LIMIT_WINDOW_SECONDS", "47")
    scopes = TOKEN_PRESET_SCOPES[preset]
    credentials = SimpleNamespace(domain="clinic.example.test", scopes=scopes, source="bearer",
                                  api_key="secret", account_id=42, bearer_token_id=99)
    result = build_whoami(credentials)
    assert result["clinic_domain"] == "clinic.example.test"
    assert result["scopes"] == list(scopes)
    assert result["access_summary"] == dict(summarize_access(scopes))
    assert list(result["access_summary"]) == ["Чтение", "Изменение", "Удаление"]
    assert result["access_summary"]["Удаление"]
    if preset == "read_only":
        assert result["access_summary"]["Удаление"] == "нет"
    assert result["groups"] == [TOKEN_PRESET_LABELS[preset]]
    assert result["limits"]["subject"] == "token"
    assert result["limits"]["requests"] == rate_limit.get_bearer_rate_limit_requests() == 317
    assert result["limits"]["window_seconds"] == rate_limit.get_bearer_rate_limit_window_seconds() == 47
    assert "secret" not in str(result)
    assert "42" not in str(result)
    assert "99" not in str(result)


def test_custom_effective_scopes_are_not_mislabelled_as_groups():
    from tools.whoami import build_whoami

    scopes = ("clients.read",)
    result = build_whoami(SimpleNamespace(domain="clinic.example.test", scopes=scopes, source="oauth"))
    assert result["groups"] == []
    assert result["scopes"] == ["clients.read"]
    assert result["access_summary"]["Удаление"] == "нет"
    assert result["limits"]["subject"] == "oauth_grant"


@pytest.mark.asyncio
async def test_whoami_is_explicitly_registered_and_visible_to_any_authorized_token():
    from server import mcp

    assert TOOL_REQUIRED_SCOPES["whoami"] == ()
    assert "whoami" in BASELINE_ALLOWED_TOOLS
    registered = {tool.name: tool for tool in await mcp.list_tools()}
    assert "whoami" in registered
    tool = registered["whoami"]
    assert tool.to_mcp_tool().inputSchema["properties"] == {}
    for scopes in TOKEN_PRESET_SCOPES.values():
        assert visible_tools_for_scopes([tool], scopes) == [tool]
    assert visible_tools_for_scopes([tool], ()) == []


@pytest.mark.asyncio
async def test_registered_tool_uses_authenticated_runtime_without_upstream(monkeypatch):
    from server import mcp

    scopes = TOKEN_PRESET_SCOPES["read_only"]
    credentials = SimpleNamespace(domain="clinic.example.test", scopes=scopes, source="bearer",
                                  account_id=None, bearer_token_id=None, is_depersonalized=False)

    async def resolve():
        return credentials

    monkeypatch.setattr("tools.resolve_runtime_credentials", resolve)
    result = (await mcp.call_tool("whoami", {})).structured_content
    assert result["clinic_domain"] == "clinic.example.test"
    assert result["groups"] == [TOKEN_PRESET_LABELS["read_only"]]
    credentials.scopes = ()
    with pytest.raises((ScopeDeniedToolError, ToolError)):
        await mcp.call_tool("whoami", {})

    async def invalid():
        raise AuthError("Invalid authorization.")

    monkeypatch.setattr("tools.resolve_runtime_credentials", invalid)
    with pytest.raises(ToolError):
        await mcp.call_tool("whoami", {})
