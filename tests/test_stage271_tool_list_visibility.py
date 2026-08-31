"""Stage 271 — the catalogue shows what the token can actually call.

`tools/list` used to be identical for everyone, so a read-only key advertised
`delete_client` and `send_message_to_all` and only found out on the call. That
is what made a reader of our own service conclude the token "gives full access
to the clinic database": they were counting the server's catalogue, not their
rights.

The filter uses the same rule as the refusal, so the two cannot drift apart.
"""

from types import SimpleNamespace

import pytest

from tool_access_registry import (
    PRESET_FULL_ACCESS,
    TOKEN_PRESET_CHOICES,
    TOKEN_PRESET_SCOPES,
    TOOL_REQUIRED_SCOPES,
)
from tool_scope_security import (
    BASELINE_ALLOWED_TOOLS,
    ScopeDeniedToolError,
    _ensure_tool_scopes_allowed,
    visible_tools_for_scopes,
)


def _visible(preset, tools):
    return {tool.name for tool in visible_tools_for_scopes(tools, TOKEN_PRESET_SCOPES[preset])}


class _Tool:
    def __init__(self, name):
        self.name = name
        self.meta = {"securitySchemes": [{"type": "oauth2", "scopes": list(TOOL_REQUIRED_SCOPES.get(name, ()))}]}


ALL_TOOLS = [_Tool(name) for name in sorted(TOOL_REQUIRED_SCOPES)]


@pytest.mark.parametrize("preset", TOKEN_PRESET_CHOICES)
def test_the_catalogue_matches_what_the_token_may_call(preset):
    """Not a hand-written list of names: every tool is checked against the
    refusal itself, so a future scope change cannot make the two disagree."""
    visible = _visible(preset, ALL_TOOLS)

    for tool in ALL_TOOLS:
        credentials = SimpleNamespace(scopes=TOKEN_PRESET_SCOPES[preset])
        try:
            _ensure_tool_scopes_allowed(tool.name, credentials)
        except ScopeDeniedToolError:
            assert tool.name not in visible, f"{preset} sees {tool.name} but cannot call it"
        else:
            assert tool.name in visible, f"{preset} may call {tool.name} but does not see it"


def test_a_read_only_key_no_longer_advertises_destructive_tools():
    visible = _visible("read_only", ALL_TOOLS)

    assert "delete_client" not in visible
    assert "delete_pet" not in visible
    assert "send_message_to_all" not in visible
    assert "create_report_ai_job" not in visible
    assert "get_clients" in visible


def test_front_desk_sees_its_own_work_and_not_the_rest():
    visible = _visible("frontdesk", ALL_TOOLS)

    assert "create_client" in visible
    assert "update_admission" in visible
    assert "delete_client" not in visible
    assert "get_medical_cards" not in visible


def test_full_access_sees_everything():
    assert _visible(PRESET_FULL_ACCESS, ALL_TOOLS) == {tool.name for tool in ALL_TOOLS}


@pytest.mark.parametrize("preset", TOKEN_PRESET_CHOICES)
def test_tools_that_need_no_rights_stay_visible(preset):
    visible = _visible(preset, ALL_TOOLS)

    for name in BASELINE_ALLOWED_TOOLS:
        assert name in visible, name


def test_a_token_without_any_rights_sees_nothing():
    assert visible_tools_for_scopes(ALL_TOOLS, ()) == []


def test_filtering_keeps_the_objects_it_was_given():
    """Rebuilding the list would drop the OAuth metadata each tool carries."""
    visible = visible_tools_for_scopes(ALL_TOOLS, TOKEN_PRESET_SCOPES["read_only"])

    assert all(tool in ALL_TOOLS for tool in visible)
    assert all(tool.meta["securitySchemes"] for tool in visible if TOOL_REQUIRED_SCOPES[tool.name])


class _FakeRequest:
    """Enough of a request for the logging path, which stamps a correlation id
    onto `request.state`."""

    def __init__(self):
        self.state = SimpleNamespace()
        self.headers = {}


def _install_http_request(monkeypatch, present: bool):
    from fastmcp.server import dependencies as fastmcp_dependencies

    def _get_http_request():
        if not present:
            raise RuntimeError("no http request")
        return _FakeRequest()

    monkeypatch.setattr(fastmcp_dependencies, "get_http_request", _get_http_request)


async def _list_through_middleware(monkeypatch, *, http, peek):
    import tool_scope_security
    from tool_scope_security import ToolVisibilityMiddleware

    _install_http_request(monkeypatch, http)
    monkeypatch.setattr(tool_scope_security, "peek_runtime_scopes", peek)

    async def call_next(_context):
        return ALL_TOOLS

    return await ToolVisibilityMiddleware().on_list_tools(object(), call_next)


@pytest.mark.asyncio
async def test_the_middleware_filters_an_authenticated_catalogue(monkeypatch):
    """Through the middleware, not the helper: a filter nobody calls is green
    and useless — that is how stage 264 shipped an unreachable message."""

    async def peek():
        return TOKEN_PRESET_SCOPES["read_only"]

    tools = await _list_through_middleware(monkeypatch, http=True, peek=peek)

    names = {tool.name for tool in tools}
    assert "delete_client" not in names
    assert "get_clients" in names


@pytest.mark.asyncio
async def test_discovery_without_a_token_keeps_the_whole_catalogue(monkeypatch):
    from exceptions import AuthError

    async def peek():
        raise AuthError("no token", status_code=401)

    tools = await _list_through_middleware(monkeypatch, http=True, peek=peek)

    assert len(tools) == len(ALL_TOOLS)


@pytest.mark.asyncio
async def test_a_failure_of_ours_keeps_the_catalogue_and_is_logged(monkeypatch, caplog):
    async def peek():
        raise RuntimeError("database is away")

    with caplog.at_level("WARNING"):
        tools = await _list_through_middleware(monkeypatch, http=True, peek=peek)

    assert len(tools) == len(ALL_TOOLS)
    assert "tool_visibility_scope_lookup_failed" in caplog.text


@pytest.mark.asyncio
async def test_a_non_http_transport_is_left_alone(monkeypatch):
    async def peek():  # pragma: no cover - must not be reached
        raise AssertionError("rights were looked up for a transport that has none")

    tools = await _list_through_middleware(monkeypatch, http=False, peek=peek)

    assert len(tools) == len(ALL_TOOLS)


def test_the_middleware_is_actually_registered():
    """A filter that is never wired into the server is a green test and a lying
    catalogue."""
    import server
    from tool_scope_security import ToolVisibilityMiddleware

    assert any(
        isinstance(middleware, ToolVisibilityMiddleware)
        for middleware in server.mcp.middleware
    )
