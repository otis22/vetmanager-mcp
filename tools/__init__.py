from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
import inspect
from functools import wraps

import depersonalization
from agent_feedback_service import augment_tool_error, should_skip_report_hint
from exceptions import AuthError
from runtime_auth import use_runtime_credentials
from service_metrics import record_sanitizer_failure
from tool_scope_security import (
    BASELINE_ALLOWED_TOOLS,
    AuthChallengeToolError,
    ScopeDeniedToolError,
    SCOPE_DENIED_MESSAGE,
    _ensure_tool_scopes_allowed,
)
from tool_access_registry import (
    TOOL_REQUIRED_SCOPES,
)
from vetmanager_client import resolve_runtime_credentials


def _wrap_tool_with_depersonalization(tool_func, *, tool_name: str | None = None):
    resolved_tool_name = tool_name or tool_func.__name__

    @wraps(tool_func)
    async def _wrapped(*args, **kwargs):
        try:
            credentials = await resolve_runtime_credentials()
        except AuthError as exc:
            raise AuthChallengeToolError(
                "Runtime authentication failed.",
                required_scopes=TOOL_REQUIRED_SCOPES.get(resolved_tool_name),
                error=exc.error_code or "invalid_token",
                error_description="OAuth authorization is required for this tool.",
            ) from None
        _ensure_tool_scopes_allowed(resolved_tool_name, credentials)

        with use_runtime_credentials(credentials):
            try:
                result = await tool_func(*args, **kwargs)
            except ToolError as exc:
                if resolved_tool_name in BASELINE_ALLOWED_TOOLS:
                    raise
                if should_skip_report_hint(exc):
                    raise
                raise await augment_tool_error(resolved_tool_name, credentials, exc) from exc
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
    from tools.feedback import register as register_feedback
    from tools.report_ai import register as register_report_ai

    register_feedback(tool_mcp)
    register_report_ai(tool_mcp)
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
