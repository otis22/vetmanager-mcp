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

        Call report_problem when a tool error is unclear or even when the tool call succeeded
        but the result does not let you answer the user well:
        empty result but relevant records were expected; response is missing fields needed to answer;
        tool description/docs promised or implied a capability that the result does not provide;
        missing tool, parameter, filter, sort, pagination, or date semantics blocks a reasonable request;
        workaround was necessary because no direct tool or parameter exists;
        successful response is suspicious, inconsistent, or not enough to answer.
        Do not call report_problem for legitimately empty results, expected
        pagination endings, correct rejections of invalid user input, or normal
        multi-step composition.

        Do not paste raw tool response bodies, raw record IDs, user's verbatim message,
        or full error payloads. Do not include bearer tokens, API keys,
        passwords, raw client or patient data, or raw Vetmanager payloads. Use
        params_shape for safe parameter names only, never parameter values.
        Describe the shape of the problem, not the data: write "client <client> lookup returns 500"
        instead of naming the client; write "patient <patient> invoice is missing" instead of naming the patient. Use
        placeholders <client>, <owner>, <patient>, <phone>, and <address>.
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
