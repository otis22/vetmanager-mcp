"""Agent feedback tools."""

from fastmcp import FastMCP

from agent_feedback_service import create_feedback_report
from request_context import get_current_request_context
from runtime_auth import get_current_runtime_credentials


def register(mcp: FastMCP) -> None:
    @mcp.tool
    async def report_problem(
        category: str,
        severity: str,
        summary: str,
        details: str,
        related_tool: str = "",
        related_call_id: str = "",
        http_status: int | None = None,
        error_code: str = "",
        error_excerpt: str = "",
        params_shape: list[str] | None = None,
        suggested_fix: str = "",
        reproduce: str = "",
    ) -> dict:
        """Report a suspected Vetmanager MCP problem for developer triage.

        Call this when a tool error is unclear, a tool description mismatches
        behavior, a reasonable user request lacks a tool or parameter, a tool
        response shape looks suspicious, or docs/examples conflict with real
        behavior. Do not include bearer tokens, API keys, passwords, raw client
        or patient data, or raw Vetmanager payloads. Use params_shape for safe
        parameter names only, never parameter values. Describe the shape of the
        problem, not the data: write "client <client> lookup returns 500" instead
        of naming the client; write "patient <patient> invoice is missing" instead
        of naming the patient. Use placeholders <client>, <owner>, <patient>,
        <phone>, and <address>.
        """
        credentials = get_current_runtime_credentials()
        if credentials is None:
            raise RuntimeError("Runtime credentials were not initialized.")
        context = get_current_request_context()
        return await create_feedback_report(
            credentials=credentials,
            category=category,
            severity=severity,
            summary=summary,
            details=details,
            related_tool=related_tool or None,
            related_call_id=related_call_id or None,
            request_id=context.get("request_id"),
            http_status=http_status,
            error_code=error_code or None,
            error_excerpt=error_excerpt or None,
            params_shape=params_shape,
            suggested_fix=suggested_fix or None,
            reproduce=reproduce or None,
        )
