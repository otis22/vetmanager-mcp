"""Stage 265.1: every scope denial an agent can hit must explain itself.

Stage 264 improved this text in `vetmanager_client`, one layer below the check
that actually fires — so agents kept reading the old wording while the tests
stayed green. The lesson is not "remember to check the layer"; it is to walk
in through the same door the agent uses, for every tool at once.

Driven by the access registry, so a tool added later is covered without
touching this file.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastmcp.exceptions import ToolError

import tools
from tests.runtime_factories import make_runtime_credentials
from tool_access_registry import TOOL_REQUIRED_SCOPES
from token_scopes import SCOPE_CLIENTS_READ

# Tools reachable with any non-empty token; their denial is a different case,
# covered in tests/test_stage264_scope_denial_is_explained.py.
from tool_scope_security import BASELINE_ALLOWED_TOOLS

_RESTRICTED_TOOLS = sorted(
    name for name in TOOL_REQUIRED_SCOPES if name not in BASELINE_ALLOWED_TOOLS
)


def _token_without(scopes: tuple[str, ...]):
    """A token that is real but lacks what this tool needs."""
    granted = tuple(scope for scope in (SCOPE_CLIENTS_READ,) if scope not in set(scopes))
    return make_runtime_credentials("clinic", "key", scopes=granted or ("pets.read",))


@pytest.mark.parametrize("tool_name", _RESTRICTED_TOOLS)
@pytest.mark.asyncio
async def test_denial_names_the_capability_and_the_next_step(tool_name, monkeypatch):
    required = TOOL_REQUIRED_SCOPES[tool_name]
    credentials = _token_without(required)
    if set(required).issubset(set(credentials.scopes)):
        pytest.skip(f"{tool_name} is satisfied by the baseline token used here")

    monkeypatch.setattr(tools, "resolve_runtime_credentials", AsyncMock(return_value=credentials))

    body_ran = False

    async def tool_func():
        nonlocal body_ran
        body_ran = True
        return {"ok": True}

    wrapped = tools._wrap_tool_with_depersonalization(tool_func, tool_name=tool_name)

    with pytest.raises(ToolError) as denied:
        await wrapped()

    # The preflight must stop the call, not merely decorate its failure.
    assert body_ran is False, f"{tool_name} executed its body despite missing scopes"

    message = str(denied.value)
    assert tool_name in message, "the message must name the tool the agent asked for"
    assert "exists but is not permitted" in message, (
        "the agent has to learn the capability is real, or it reports it as missing"
    )
    assert "Allowed presets:" in message, "name the access that would grant it"
    assert "administrator" in message.lower() or "no scopes" in message.lower(), (
        "say what to do next; a bare denial makes the agent retry or give up"
    )


def test_the_registry_is_not_empty():
    """A silent registry would make every case above vacuously pass."""
    assert len(_RESTRICTED_TOOLS) > 50


@pytest.mark.asyncio
async def test_the_http_connector_receives_the_same_explanation(monkeypatch):
    """The HTTP path answers before the wrapper, with its own result shape.

    Both paths share the formatter, so the words are the same — but the
    envelope is not, and a change to it would leave the connector's users with
    an empty bubble while the stdio tests stayed green.
    """
    from types import SimpleNamespace

    import tool_oauth_security as oauth_security

    credentials = make_runtime_credentials("clinic", "key", scopes=(SCOPE_CLIENTS_READ,))
    monkeypatch.setattr(oauth_security, "_is_http_mcp_request", lambda: True)
    monkeypatch.setattr(
        oauth_security, "resolve_runtime_credentials", AsyncMock(return_value=credentials)
    )

    middleware = oauth_security.OAuthChallengeMiddleware()
    context = SimpleNamespace(message=SimpleNamespace(name="save_report_ai_job_as_report"))

    async def call_next(_context):  # pragma: no cover - must not be reached
        raise AssertionError("the denied tool must not be forwarded")

    result = await middleware.on_call_tool(context, call_next)

    # The middleware hands back a wrapper; what the connector sends is inside.
    mcp_result = result.to_mcp_result()
    text = mcp_result.content[0].text
    assert "save_report_ai_job_as_report" in text
    assert "exists but is not permitted" in text
    assert "Allowed presets:" in text
    assert mcp_result.isError is True
