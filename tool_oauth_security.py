"""OpenAI Apps OAuth auth metadata for MCP tools/list."""

from __future__ import annotations

from fastmcp import FastMCP

from tool_access_registry import TOOL_REQUIRED_SCOPES


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
