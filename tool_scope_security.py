"""Shared MCP tool scope enforcement policy."""

from __future__ import annotations

import logging

from fastmcp.exceptions import ToolError
from fastmcp.server import dependencies as _fastmcp_dependencies
from fastmcp.server.middleware import Middleware

from exceptions import AuthError
from runtime_auth import peek_runtime_scopes
from tool_access_registry import (
    BASELINE_ALLOWED_TOOLS,
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    get_token_preset_label,
    infer_token_preset,
)



class AuthChallengeToolError(ToolError):
    def __init__(
        self,
        message: str,
        *,
        required_scopes: tuple[str, ...] | None,
        error: str,
        error_description: str,
    ) -> None:
        super().__init__(message)
        self.required_scopes = tuple(sorted(required_scopes or ()))
        self.error = error
        self.error_description = error_description


class ScopeDeniedToolError(AuthChallengeToolError):
    def __init__(self, message: str, *, required_scopes: tuple[str, ...] | None) -> None:
        super().__init__(
            message,
            required_scopes=required_scopes,
            error="insufficient_scope",
            error_description="The token does not grant the scopes required for this tool.",
        )


def _format_scope_denied_message(
    tool_name: str,
    *,
    required_scopes: tuple[str, ...] | None,
    token_scopes: tuple[str, ...],
) -> str:
    required = tuple(sorted(required_scopes or ()))
    granted = tuple(sorted(token_scopes))
    missing = tuple(scope for scope in required if scope not in set(granted))
    inferred_preset = infer_token_preset(granted)
    current_preset = (
        get_token_preset_label(inferred_preset)
        if inferred_preset is not None
        else "custom scopes"
    )
    allowed_presets = get_presets_allowing_tool(tool_name)
    allowed = ", ".join(allowed_presets) if allowed_presets else "none"
    required_text = ", ".join(required) if required else "unmapped tool"
    missing_text = ", ".join(missing) if missing else "unknown"
    # Stage 264: this is the text an agent actually reads — the tool-level
    # check runs before any upstream call. It has to answer three questions at
    # once: the capability exists, what access it needs in the words the
    # account page uses, and what to do now. Without the last part an agent
    # either retries the same call or tells the user the feature is missing.
    # Deliberately not "clinic administrator" anywhere below: the word `clinic`
    # is barred from these messages, because a test guards against the clinic
    # domain leaking into an error an agent may repeat back to a user.
    if not granted:
        # Baseline tools need no particular preset — they need a token that
        # carries any rights at all. Telling this reader that no preset grants
        # the tool sends them hunting for a permission that does not exist.
        next_step = (
            "This token carries no scopes at all. Reconnect with a token that has "
            "access, then call this tool again."
        )
    elif allowed_presets:
        next_step = (
            "Ask your account administrator for a token with one of those presets; "
            "repeating this call with the current token will fail the same way."
        )
    else:
        next_step = "No access preset grants this tool; do not retry."
    return (
        f"Tool '{tool_name}' exists but is not permitted for this token. "
        f"Required scopes: {required_text}. "
        f"Missing scopes: {missing_text}. "
        f"Current preset: {current_preset}. "
        f"Allowed presets: {allowed}. "
        f"{next_step}"
    )


def _ensure_tool_scopes_allowed(tool_name: str, credentials) -> None:
    token_scopes = tuple(getattr(credentials, "scopes", ()) or ())
    if tool_name in BASELINE_ALLOWED_TOOLS:
        if not token_scopes:
            raise ScopeDeniedToolError(
                _format_scope_denied_message(
                    tool_name,
                    required_scopes=(),
                    token_scopes=token_scopes,
                ),
                required_scopes=(),
            )
        return
    required_scopes = TOOL_REQUIRED_SCOPES.get(tool_name)
    if not required_scopes or not token_scopes:
        raise ScopeDeniedToolError(
            _format_scope_denied_message(
                tool_name,
                required_scopes=required_scopes,
                token_scopes=token_scopes,
            ),
            required_scopes=required_scopes,
        )
    if not set(required_scopes).issubset(set(token_scopes)):
        raise ScopeDeniedToolError(
            _format_scope_denied_message(
                tool_name,
                required_scopes=required_scopes,
                token_scopes=token_scopes,
            ),
            required_scopes=required_scopes,
        )


RUNTIME_LOGGER = logging.getLogger("vetmanager_mcp.runtime")


def visible_tools_for_scopes(tools, token_scopes):
    """The subset of `tools` this token may actually call.

    Deliberately the same rule as `_ensure_tool_scopes_allowed`, expressed once:
    a catalogue that disagrees with the refusal is worse than no filtering at
    all, because then the list lies in a new way.

    The given objects are returned as they are — never rebuilt — so the OAuth
    metadata attached to each tool survives.
    """
    granted = set(token_scopes or ())
    if not granted:
        return []

    visible = []
    for tool in tools:
        if tool.name in BASELINE_ALLOWED_TOOLS:
            visible.append(tool)
            continue
        required = TOOL_REQUIRED_SCOPES.get(tool.name)
        if required and set(required).issubset(granted):
            visible.append(tool)
    return visible


class ToolVisibilityMiddleware(Middleware):
    """Stage 271: show a token the tools it can use, not the whole catalogue.

    Only `on_list_tools` is implemented, so the call path stays exactly as it
    was. The list is left whole whenever the rights cannot be established —
    an unauthenticated discovery call, a non-HTTP transport, or a failure that
    has nothing to do with authentication. Hiding everything would present the
    service as having no tools at all; the call check still guards access.
    """

    async def on_list_tools(self, context, call_next):
        tools = await call_next(context)

        try:
            _fastmcp_dependencies.get_http_request()
        except RuntimeError:
            return tools

        try:
            token_scopes = await peek_runtime_scopes()
        except AuthError:
            # No token, or one that is not valid — the ordinary discovery call.
            return tools
        except Exception:
            # Anything else is a failure of ours, not of the caller. Serve the
            # catalogue rather than an empty service, but say so: a full list
            # returned quietly would hide the outage behind normal-looking
            # output.
            RUNTIME_LOGGER.warning(
                "tool_visibility_scope_lookup_failed",
                exc_info=True,
                extra={"event": "tool_visibility_scope_lookup_failed"},
            )
            return tools

        if token_scopes is None:
            return tools
        return visible_tools_for_scopes(tools, token_scopes)
