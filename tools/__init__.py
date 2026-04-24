from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import inspect
from functools import wraps

import depersonalization
from exceptions import AuthError
from runtime_auth import use_runtime_credentials
from service_metrics import record_sanitizer_failure
from tool_access_registry import (
    TOOL_REQUIRED_SCOPES,
    get_presets_allowing_tool,
    get_token_preset_label,
    infer_token_preset,
)
from vetmanager_client import resolve_runtime_credentials


SCOPE_DENIED_MESSAGE = "Tool is not permitted for this token."


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
    required_scopes = TOOL_REQUIRED_SCOPES.get(tool_name)
    token_scopes = tuple(getattr(credentials, "scopes", ()) or ())
    if not required_scopes or not token_scopes:
        raise ToolError(
            _format_scope_denied_message(
                tool_name,
                required_scopes=required_scopes,
                token_scopes=token_scopes,
            )
        )
    if not set(required_scopes).issubset(set(token_scopes)):
        raise ToolError(
            _format_scope_denied_message(
                tool_name,
                required_scopes=required_scopes,
                token_scopes=token_scopes,
            )
        )


def _wrap_tool_with_depersonalization(tool_func, *, tool_name: str | None = None):
    resolved_tool_name = tool_name or tool_func.__name__

    @wraps(tool_func)
    async def _wrapped(*args, **kwargs):
        try:
            credentials = await resolve_runtime_credentials()
        except AuthError:
            raise ToolError("Runtime authentication failed.") from None
        _ensure_tool_scopes_allowed(resolved_tool_name, credentials)

        with use_runtime_credentials(credentials):
            result = await tool_func(*args, **kwargs)
            if not credentials.is_depersonalized:
                return result
            try:
                return depersonalization.sanitize_tool_result(result)
            except Exception:
                record_sanitizer_failure()
                raise ToolError("Depersonalization failed.") from None

    _wrapped.__signature__ = inspect.signature(tool_func)
    return _wrapped


class _ToolRegistrationProxy:
    def __init__(self, mcp: FastMCP) -> None:
        self._mcp = mcp

    def tool(self, func=None, **kwargs):
        if func is None:
            def _decorator(actual_func):
                tool_name = kwargs.get("name") or actual_func.__name__
                return self._mcp.tool(
                    _wrap_tool_with_depersonalization(actual_func, tool_name=tool_name),
                    **kwargs,
                )

            return _decorator
        tool_name = kwargs.get("name") or func.__name__
        return self._mcp.tool(_wrap_tool_with_depersonalization(func, tool_name=tool_name), **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._mcp, name)


def register_all(mcp: FastMCP) -> None:
    """Register all entity tool modules with the MCP server."""
    tool_mcp = _ToolRegistrationProxy(mcp)
    from tools.client import register as register_client
    from tools.pet import register as register_pet
    from tools.admission import register as register_admission
    from tools.medical_card import register as register_medical_card
    from tools.invoice import register as register_invoice
    from tools.good import register as register_good
    from tools.user import register as register_user
    from tools.reference import register as register_reference
    from tools.finance import register as register_finance
    from tools.warehouse import register as register_warehouse
    from tools.clinical import register as register_clinical
    from tools.operations import register as register_operations
    from tools.schedule import register as register_schedule

    register_client(tool_mcp)
    register_pet(tool_mcp)
    register_admission(tool_mcp)
    register_medical_card(tool_mcp)
    register_invoice(tool_mcp)
    register_good(tool_mcp)
    register_user(tool_mcp)
    register_reference(tool_mcp)
    register_finance(tool_mcp)
    register_warehouse(tool_mcp)
    register_clinical(tool_mcp)
    register_operations(tool_mcp)
    register_schedule(tool_mcp)
