"""OpenAI Apps OAuth auth metadata for MCP tools/list."""

from __future__ import annotations

from fastmcp import FastMCP
from fastmcp.server import dependencies as _fastmcp_dependencies
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

from exceptions import AuthError
from oauth_challenge import oauth_challenge_details
from runtime_auth import use_runtime_credentials
from tool_access_registry import TOOL_REQUIRED_SCOPES
from tool_scope_security import AuthChallengeToolError, _ensure_tool_scopes_allowed
from vetmanager_client import resolve_runtime_credentials


def _oauth_security_scheme(scopes: tuple[str, ...]) -> dict:
    return {
        "type": "oauth2",
        "scopes": list(scopes),
    }


def apply_tool_oauth_security_metadata(mcp: FastMCP) -> None:
    """Attach OAuth `securitySchemes` metadata to registered FastMCP tools."""
    provider = getattr(mcp, "_local_provider", None)
    components = getattr(provider, "_components", None)
    if not isinstance(components, dict):
        return

    for key, component in components.items():
        if not key.startswith("tool:"):
            continue

        scopes = TOOL_REQUIRED_SCOPES.get(component.name, ())
        metadata = dict(getattr(component, "meta", None) or {})
        metadata["securitySchemes"] = [_oauth_security_scheme(tuple(scopes))]
        component.meta = metadata


def _scope_challenge_value(required_scopes: tuple[str, ...] | None) -> str | None:
    scopes = tuple(sorted(required_scopes or ()))
    if not scopes:
        return None
    return " ".join(scopes)


class OAuthChallengeToolResult:
    def __init__(self, result: CallToolResult) -> None:
        self._result = result

    def to_mcp_result(self) -> CallToolResult:
        return self._result


def _is_http_mcp_request() -> bool:
    try:
        _fastmcp_dependencies.get_http_request()
    except RuntimeError:
        return False
    return True


def _challenge_result(exc) -> OAuthChallengeToolResult:
    return OAuthChallengeToolResult(
        CallToolResult(
            content=[TextContent(type="text", text=str(exc))],
            isError=True,
            **{
                "_meta": oauth_challenge_details(
                    scope=_scope_challenge_value(exc.required_scopes),
                    error=exc.error,
                    error_description=exc.error_description,
                )
            },
        )
    )


class OAuthChallengeMiddleware(Middleware):
    async def on_call_tool(
        self,
        context: MiddlewareContext[CallToolRequestParams],
        call_next,
    ):
        if _is_http_mcp_request():
            tool_name = context.message.name
            if tool_name not in TOOL_REQUIRED_SCOPES:
                return await call_next(context)
            try:
                credentials = await resolve_runtime_credentials()
            except AuthError as exc:
                return _challenge_result(
                    AuthChallengeToolError(
                        "Runtime authentication failed.",
                        required_scopes=TOOL_REQUIRED_SCOPES.get(tool_name),
                        error=exc.error_code or "invalid_token",
                        error_description="OAuth authorization is required for this tool.",
                    )
                )
            try:
                _ensure_tool_scopes_allowed(tool_name, credentials)
            except AuthChallengeToolError as exc:
                return _challenge_result(exc)
            with use_runtime_credentials(credentials):
                return await call_next(context)

        return await call_next(context)
