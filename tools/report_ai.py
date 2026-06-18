"""Report AI job tools for Vetmanager report constructor workflows."""

import json
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from exceptions import AuthError, VetmanagerError
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


def _validate_positive_int(name: str, value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolError(f"{name} must be a positive integer.") from None
    if number <= 0:
        raise ToolError(f"{name} must be a positive integer.")
    return number


def _report_filter_params(report_id: int, filter_json: str | None = None) -> dict[str, str | int]:
    params: dict[str, str | int] = {"report_id": _validate_positive_int("report_id", report_id)}
    filter_value = (filter_json or "").strip()
    if not filter_value:
        return params
    try:
        json.loads(filter_value)
    except json.JSONDecodeError as exc:
        raise ToolError("filter_json must be valid JSON when provided.") from exc
    params["filter"] = filter_value
    return params


def _extract_job(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("job"), dict):
        return data["job"]
    if isinstance(payload.get("job"), dict):
        return payload["job"]
    return {}


def _extract_report(payload: dict) -> dict:
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("report"), dict):
        return data["report"]
    if isinstance(payload.get("report"), dict):
        return payload["report"]
    return {}


def _ensure_start_report_payload(payload: dict) -> dict:
    if payload.get("success") is False:
        raise ToolError("Starting report export failed.")
    report = _extract_report(payload)
    if not report.get("report_file_id"):
        raise ToolError("Starting report export failed: report_file_id is missing.")
    return payload


def _ensure_report_file_payload(payload: dict) -> dict:
    if payload.get("success") is False:
        raise ToolError("Getting report export file failed.")
    report = _extract_report(payload)
    if not any(
        report.get(name)
        for name in ("html_file", "csv_file", "csv_semicolon_file", "xlsx_file")
    ):
        raise ToolError("Getting report export file failed: export file fields are missing.")
    return payload


def _safe_export_error(
    exc: VetmanagerError,
    action: str,
    *,
    retry_on_conflict: bool = False,
) -> ToolError:
    if isinstance(exc, AuthError) and "lacks required scope" in str(exc):
        return _tool_error_from_vm(exc)
    status = f" HTTP {exc.status_code}" if exc.status_code is not None else ""
    code = f" ({exc.error_code})" if exc.error_code else ""
    lowered = str(exc).lower()
    if retry_on_conflict and exc.status_code == 409:
        return ToolError(
            "Report export is not ready yet; call get_report_export_file again after a delay."
        )
    if "build in progress" in lowered or "not started" in lowered:
        return ToolError(
            "Report export is not ready yet; call get_report_export_file again after a delay."
        )
    if exc.status_code == 403:
        return ToolError(
            "Report is not REST-exportable or export is rate-limited: "
            "Vetmanager denied StartReport for this report_id. "
            "Use a Report Constructor report with REST access enabled and retry later if needed."
        )
    return ToolError(f"{action} failed{status}{code}.")


async def _call_vm(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
) -> dict:
    client = VetmanagerClient()
    try:
        if method == "GET":
            return await client.get(path, params=params)
        if method == "POST":
            return await client.post(path, json=json or {})
    except VetmanagerError as exc:
        raise _tool_error_from_vm(exc) from None
    raise RuntimeError(f"Unsupported Report AI method: {method}")


async def _start_report_export(report_id: int, filter_json: str | None = None) -> dict:
    params = _report_filter_params(report_id, filter_json)
    client = VetmanagerClient()
    try:
        payload = await client.get("/rest/api/report/StartReport", params=params, retry=False)
        return _ensure_start_report_payload(payload)
    except VetmanagerError as exc:
        raise _safe_export_error(exc, "Starting report export") from None


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

    @mcp.tool
    async def start_report_export(report_id: int, filter_json: str | None = None) -> dict:
        """Start Vetmanager Report Constructor CSV/XLSX export for a known report ID.

        Args:
            report_id: Existing Report Constructor report ID with REST export enabled.
            filter_json: Optional report-specific JSON filter. Omitted when empty;
                MCP validates JSON syntax only, not report-specific semantics.
        """
        return await _start_report_export(report_id, filter_json)

    @mcp.tool
    async def get_report_export_file(report_file_id: int) -> dict:
        """Get CSV/XLSX export file locators after start_report_export.

        Args:
            report_file_id: Export build ID returned by start_report_export.
                If Vetmanager says generation is still in progress, retry this
                tool after a delay.
        """
        file_id = _validate_positive_int("report_file_id", report_file_id)
        client = VetmanagerClient()
        try:
            payload = await client.get("/rest/api/report/reportFile", params={"file_id": file_id})
            return _ensure_report_file_payload(payload)
        except VetmanagerError as exc:
            raise _safe_export_error(
                exc, "Getting report export file", retry_on_conflict=True
            ) from None

    @mcp.tool
    async def get_report_ai_job_export(job_id: int, filter_json: str | None = None) -> dict:
        """Start CSV/XLSX export for a saved or existing-matched Report AI job.

        Args:
            job_id: Report AI job ID. The job must be saved or
                existing_report_matched and include job.report_id. This tool does
                not auto-save ready_to_save jobs.
            filter_json: Optional report-specific JSON filter passed to
                start_report_export when non-empty.
        """
        safe_job_id = _validate_positive_int("job_id", job_id)
        job_payload = await _call_vm("GET", f"/rest/api/report-ai-job/{safe_job_id}")
        job = _extract_job(job_payload)
        status = str(job.get("status") or "")
        if status not in {"saved", "existing_report_matched"}:
            raise ToolError(
                "Report AI job must be saved or existing_report_matched before export."
            )
        report_id = job.get("report_id")
        if not report_id:
            raise ToolError("Report AI job does not include report_id for export.")
        safe_report_id = _validate_positive_int("report_id", report_id)
        return await _start_report_export(safe_report_id, filter_json)
