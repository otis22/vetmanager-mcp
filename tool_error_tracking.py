"""Semantic, privacy-safe Sentry capture at the FastMCP tool boundary."""

from __future__ import annotations

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcp.types import CallToolRequestParams

from error_tracking import capture_tool_failure, mark_tool_error_as_handled
from filters import FilterPropertyValidationError
from runtime_auth import get_current_runtime_credentials


def _exception_chain_contains(exc: BaseException, expected_type: type[BaseException]) -> bool:
    seen: set[int] = set()
    while id(exc) not in seen:
        seen.add(id(exc))
        if isinstance(exc, expected_type):
            return True
        next_exc = exc.__cause__
        if not isinstance(next_exc, BaseException):
            return False
        exc = next_exc
    return False


class ToolErrorTrackingMiddleware(Middleware):
    """Capture one semantic event after OAuth has placed credentials in context."""

    async def on_call_tool(self, context: MiddlewareContext[CallToolRequestParams], call_next):
        try:
            return await call_next(context)
        except ToolError as exc:
            mark_tool_error_as_handled(exc)
            if not _exception_chain_contains(exc, FilterPropertyValidationError):
                try:
                    credentials = get_current_runtime_credentials()
                except Exception:
                    credentials = None
                capture_tool_failure(
                    exc,
                    tool_name=context.message.name,
                    account_id=getattr(credentials, "account_id", None),
                )
            raise
