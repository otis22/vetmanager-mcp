"""Describe the effective access of the current MCP credential."""

from fastmcp import FastMCP

from access_summary import summarize_access
from auth.rate_limit import (
    get_bearer_rate_limit_requests,
    get_bearer_rate_limit_window_seconds,
)
from runtime_auth import get_current_runtime_credentials
from tool_access_registry import TOKEN_PRESET_LABELS, infer_token_preset


def build_whoami(credentials) -> dict:
    """Build the safe public identity from already authenticated credentials."""
    scopes = tuple(sorted(set(credentials.scopes)))
    preset = infer_token_preset(scopes)
    return {
        "clinic_domain": credentials.domain,
        "groups": [TOKEN_PRESET_LABELS[preset]] if preset is not None else [],
        "scopes": list(scopes),
        "access_summary": dict(summarize_access(scopes)),
        "limits": {
            "requests": get_bearer_rate_limit_requests(),
            "window_seconds": get_bearer_rate_limit_window_seconds(),
            "subject": "oauth_grant" if credentials.source == "oauth" else "token",
        },
    }


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def whoami() -> dict:
        """Show this token's clinic domain, access group, effective rights and MCP request limit.

        The summary always names reading, changing and deletion, including
        «Удаление: нет» when this token cannot delete. No Vetmanager request is made.
        Domain synonyms: кто я, мои права, мой доступ, возможности токена,
        whoami, capabilities, current clinic, access group.
        """
        credentials = get_current_runtime_credentials()
        if credentials is None:
            raise RuntimeError("Runtime credentials were not initialized.")
        return build_whoami(credentials)
