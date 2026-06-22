"""Shared MCP tool scope enforcement policy."""

from __future__ import annotations

from fastmcp.exceptions import ToolError

from tool_access_registry import (
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    get_token_preset_label,
    infer_token_preset,
)


SCOPE_DENIED_MESSAGE = "Tool is not permitted for this token."
BASELINE_ALLOWED_TOOLS = {"get_report_ai_prompt_helper", "report_problem"}


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
    return (
        f"Tool '{tool_name}' is not permitted for this token. "
        f"{SCOPE_DENIED_MESSAGE} "
        f"Required scopes: {required_text}. "
        f"Missing scopes: {missing_text}. "
        f"Current preset: {current_preset}. "
        f"Allowed presets: {allowed}."
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
