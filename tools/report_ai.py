"""Report AI job tools for Vetmanager report constructor workflows."""

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from exceptions import VetmanagerError
from vetmanager_client import VetmanagerClient


INTENT_MAX_LENGTH = 1000
_GENERIC_REPORT_TITLES = {
    "report",
    "отчет",
    "отчёт",
    "mcp report",
    "mcp отчет",
    "mcp отчёт",
    "test",
    "тест",
}


def _validate_intent_text(intent_text: str) -> str:
    intent = (intent_text or "").strip()
    if not intent:
        raise ToolError("intent_text must be non-empty.")
    if len(intent) > INTENT_MAX_LENGTH:
        raise ToolError(f"intent_text must be no longer than {INTENT_MAX_LENGTH} characters.")
    return intent


def _validate_report_title(title: str) -> str:
    value = (title or "").strip()
    if len(value) < 12 or value.lower() in _GENERIC_REPORT_TITLES:
        raise ToolError(
            "title must be meaningful: include the report purpose and period when applicable."
        )
    return value


def _tool_error_from_vm(exc: VetmanagerError) -> ToolError:
    if exc.error_code:
        return ToolError(str(exc))
    return ToolError(str(exc))


async def _call_vm(method: str, path: str, *, json: dict | None = None) -> dict:
    client = VetmanagerClient()
    try:
        if method == "GET":
            return await client.get(path)
        if method == "POST":
            return await client.post(path, json=json or {})
    except VetmanagerError as exc:
        raise _tool_error_from_vm(exc) from None
    raise RuntimeError(f"Unsupported Report AI method: {method}")


def register(mcp: FastMCP) -> None:

    @mcp.tool
    async def create_report_ai_job(intent_text: str) -> dict:
        """Create an async Vetmanager Report AI job from Russian report intent.

        Args:
            intent_text: Russian business-report request. Must be non-empty and
                no longer than 1000 characters. The job is async; poll with
                get_report_ai_job and reuse returned jobs when is_deduplicated=true.
        """
        intent = _validate_intent_text(intent_text)
        return await _call_vm(
            "POST",
            "/rest/api/report-ai-job",
            json={"intent_text": intent},
        )

    @mcp.tool
    async def get_report_ai_job(job_id: int) -> dict:
        """Get safe Report AI job status and recognized structure without raw SQL.

        Args:
            job_id: Report AI job ID. Poll queued/recognizing/building_preview
                jobs until ready_to_save, existing_report_matched,
                needs_confirmation, saved, failed, or rejected. For
                needs_confirmation, the returned job.candidates contain the
                report_id values accepted by confirm_report_ai_job_candidate.
        """
        return await _call_vm("GET", f"/rest/api/report-ai-job/{job_id}")

    @mcp.tool
    async def confirm_report_ai_job_candidate(job_id: int, report_id: int) -> dict:
        """Confirm one existing report candidate for a Report AI job.

        Args:
            job_id: Report AI job ID currently in needs_confirmation.
            report_id: Candidate report ID from get_report_ai_job job.candidates.
        """
        return await _call_vm(
            "POST",
            f"/rest/api/report-ai-job/{job_id}/confirm",
            json={"report_id": report_id},
        )

    @mcp.tool
    async def get_report_ai_job_data(job_id: int) -> dict:
        """Get rows for a saved or existing-matched Report AI job.

        Args:
            job_id: Report AI job ID. Data is available only for saved or
                existing_report_matched jobs. ready_to_save has preview summary
                only; call save_report_ai_job_as_report first when rows are
                needed. Returned rows are capped by Vetmanager at 1000 and
                limited=true means total is larger.
        """
        return await _call_vm("GET", f"/rest/api/report-ai-job/{job_id}/data")

    @mcp.tool
    async def save_report_ai_job_as_report(job_id: int, title: str) -> dict:
        """Persist a ready_to_save Report AI job as a visible Vetmanager report.

        Args:
            job_id: Report AI job ID. Save is valid only from ready_to_save;
                already saved jobs return the existing report_id idempotently.
            title: Meaningful report title visible in Vetmanager. Include
                purpose and period when applicable, for example
                'MCP debtors by negative balance 2026-06-15'.
        """
        safe_title = _validate_report_title(title)
        return await _call_vm(
            "POST",
            f"/rest/api/report-ai-job/{job_id}/save",
            json={"title": safe_title},
        )
