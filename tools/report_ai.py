"""Report AI job tools for Vetmanager report constructor workflows."""

import json
import time
from collections import OrderedDict
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from exceptions import AuthError, VetmanagerError
from observability_logging import RUNTIME_LOGGER
from prompts import get_report_ai_prompt_helper_text
from runtime_auth import get_current_runtime_credentials
from service_metrics import record_report_ai_long_queued_poll
from vetmanager_client import VetmanagerClient


INTENT_MAX_LENGTH = 20000
REPORT_AI_DATA_ROW_LIMIT = 10000
REPORT_AI_LARGE_RESULT_GUIDANCE_THRESHOLD = 9000
REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS = 30
REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS = 3600
REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES = 4096
REPORT_AI_GOODS_GOOD_ID_WORKAROUND_CODE = "report_ai_goods_good_id_preview_failed"
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
_GOODS_GOOD_ID_MARKERS = (
    "good.id",
    "`good`.`id`",
    '"good"."id"',
    "unknown column",
    "unknown field",
    "неизвестная колонка",
    "неизвестное поле",
    "неизвестный столбец",
)
_ReportAiQueueObservationKey = tuple[int | None, int | None, int]
_REPORT_AI_QUEUE_OBSERVATIONS: OrderedDict[
    _ReportAiQueueObservationKey, dict[str, float]
] = OrderedDict()


def _monotonic_seconds() -> float:
    return time.monotonic()


def _reset_report_ai_queue_observations() -> None:
    _REPORT_AI_QUEUE_OBSERVATIONS.clear()


def _report_ai_queue_observation_count() -> int:
    return len(_REPORT_AI_QUEUE_OBSERVATIONS)


def _cleanup_report_ai_queue_observations(now: float) -> None:
    expired_job_ids = [
        job_id
        for job_id, observation in _REPORT_AI_QUEUE_OBSERVATIONS.items()
        if now - observation["last_seen"] > REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS
    ]
    for job_id in expired_job_ids:
        _REPORT_AI_QUEUE_OBSERVATIONS.pop(job_id, None)
    while len(_REPORT_AI_QUEUE_OBSERVATIONS) > REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES:
        _REPORT_AI_QUEUE_OBSERVATIONS.popitem(last=False)


def _report_ai_queue_observation_key(job: dict) -> _ReportAiQueueObservationKey | None:
    job_id = job.get("id")
    try:
        normalized_job_id = int(job_id)
    except (TypeError, ValueError):
        return None
    credentials = get_current_runtime_credentials()
    return (
        credentials.account_id if credentials is not None else None,
        credentials.connection_id if credentials is not None else None,
        normalized_job_id,
    )


def _observe_report_ai_queue(job: dict, *, now: float | None = None) -> int | None:
    observation_key = _report_ai_queue_observation_key(job)

    current_time = _monotonic_seconds() if now is None else now
    _cleanup_report_ai_queue_observations(current_time)

    if job.get("status") != "queued":
        if observation_key is not None:
            _REPORT_AI_QUEUE_OBSERVATIONS.pop(observation_key, None)
        return None

    if observation_key is None:
        return None

    observation = _REPORT_AI_QUEUE_OBSERVATIONS.get(observation_key)
    if observation is None:
        observation = {"first_seen": current_time, "last_seen": current_time}
        _REPORT_AI_QUEUE_OBSERVATIONS[observation_key] = observation
    else:
        observation["last_seen"] = current_time
        _REPORT_AI_QUEUE_OBSERVATIONS.move_to_end(observation_key)

    _cleanup_report_ai_queue_observations(current_time)
    return max(0, int(current_time - observation["first_seen"]))


def _queued_age_bucket(age_seconds: int) -> str:
    if age_seconds < 60:
        return "30s_1m"
    if age_seconds < 300:
        return "1m_5m"
    if age_seconds < 900:
        return "5m_15m"
    return "15m_plus"


def _report_ai_goods_good_id_workaround() -> dict:
    return {
        "code": REPORT_AI_GOODS_GOOD_ID_WORKAROUND_CODE,
        "summary": (
            "Report AI preview failed with an explicit good.id marker. This can still "
            "happen on older Vetmanager contours or unresolved goods report edge cases."
        ),
        "steps": [
            "Check the current job status with get_report_ai_job; if it returned candidates, use confirm_report_ai_job_candidate instead of creating a duplicate job.",
            "If the job really failed with PREVIEW_FAILED and a good.id marker, read get_report_ai_prompt_helper or report_ai_prompt_helper before retrying.",
            "Rephrase the Russian intent to request product code/article/title instead of a standalone good.id column.",
            "Create a new Report AI job only after confirming there is no usable candidate or existing matched report.",
        ],
        "do_not_do": [
            "Do not ask Report AI to output a standalone good.id column.",
            "Do not expose or edit raw SQL in MCP output.",
        ],
        "safe_to_retry": True,
    }


def _looks_like_goods_good_id_preview_failure(job: dict) -> bool:
    if job.get("status") != "failed" or job.get("error_code") != "PREVIEW_FAILED":
        return False
    message = str(job.get("error_message_safe") or "").lower()
    if not message:
        return False
    if any(marker in message for marker in ("good.id", "`good`.`id`", '"good"."id"')):
        return True
    has_unknown_column_marker = any(marker in message for marker in _GOODS_GOOD_ID_MARKERS[3:])
    return has_unknown_column_marker and "good" in message and "id" in message


def _annotate_report_ai_workarounds(payload: dict) -> dict:
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else payload.get("job")
    if not isinstance(job, dict) or not _looks_like_goods_good_id_preview_failure(job):
        return payload
    job.setdefault("mcp_workaround", _report_ai_goods_good_id_workaround())
    return payload


def _annotate_report_ai_queue_diagnostics(payload: dict) -> dict:
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else payload.get("job")
    if not isinstance(job, dict):
        return payload

    observed_age_seconds = _observe_report_ai_queue(job)
    if (
        observed_age_seconds is None
        or observed_age_seconds < REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS
    ):
        return payload

    diagnostics = {
        "code": "report_ai_job_long_queued",
        "observed_queued_age_seconds": observed_age_seconds,
        "threshold_seconds": REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS,
        "status": "queued",
        "operator_hint": (
            "Continue bounded polling. If the job remains queued, inspect Report AI "
            "worker/stale in-progress diagnostics using the MCP operator runbook."
        ),
    }
    for field_name in ("created_at", "updated_at"):
        if job.get(field_name):
            diagnostics[field_name] = job[field_name]

    job.setdefault("mcp_queue_diagnostics", diagnostics)
    record_report_ai_long_queued_poll()
    RUNTIME_LOGGER.warning(
        "report_ai_job_long_queued",
        extra={
            "event_name": "report_ai_job_long_queued",
            "status": "queued",
            "threshold_seconds": REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS,
            "observed_queued_age_seconds": observed_age_seconds,
            "observed_queued_age_bucket": _queued_age_bucket(observed_age_seconds),
        },
    )
    return payload


def _annotate_report_ai_job_payload(payload: dict) -> dict:
    return _annotate_report_ai_queue_diagnostics(_annotate_report_ai_workarounds(payload))


def _annotate_report_ai_data_payload(payload: dict) -> dict:
    data = payload.get("data")
    if not isinstance(data, dict):
        return payload

    limited = data.get("limited") is True
    try:
        total = int(data.get("total"))
    except (TypeError, ValueError):
        total = None

    near_cap = total is not None and total >= REPORT_AI_LARGE_RESULT_GUIDANCE_THRESHOLD
    if not limited and not near_cap:
        return payload

    guidance = {
        "code": "report_ai_large_result",
        "row_limit": REPORT_AI_DATA_ROW_LIMIT,
        "threshold": REPORT_AI_LARGE_RESULT_GUIDANCE_THRESHOLD,
        "limited": limited,
        "total": total,
        "summary": (
            "Report AI returned a large row set. Avoid pasting huge tables into chat; "
            "narrow the report or use CSV/XLSX export for bulk review."
        ),
    }
    if data.get("csv_export_url"):
        guidance["export_available"] = True
    data.setdefault("mcp_large_result_guidance", guidance)
    return payload


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
        if "report creating in progress" in lowered:
            return ToolError(
                "Report export is already being created by Vetmanager; retry after a delay "
                "with bounded polling instead of starting duplicate exports."
            )
        if "can not run a report more than 10 minutes" in lowered:
            return ToolError(
                "Report export is temporarily limited by Vetmanager because a report has "
                "been running too long; retry later instead of starting duplicate exports."
            )
        if "not accessible for rest" in lowered:
            return ToolError(
                "Report is not REST-exportable: Vetmanager denied StartReport for this report_id."
            )
        return ToolError(
            "Report export was denied or temporarily limited by Vetmanager (HTTP 403). "
            "Retry only with bounded attempts; if it keeps failing, treat this report_id "
            "as not currently exportable."
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
    async def get_report_ai_prompt_helper() -> dict:
        """Return guidance for formulating safe Vetmanager Report AI intents.

        Use this static helper before create_report_ai_job when MCP prompts are
        not visible in the client. It returns the same text as the
        report_ai_prompt_helper prompt.
        """
        return {"helper_text": get_report_ai_prompt_helper_text()}

    @mcp.tool
    async def create_report_ai_job(intent_text: str) -> dict:
        """Create an async Vetmanager Report AI job from Russian report intent.

        Args:
            intent_text: Russian business-report request. Must be non-empty and
                no longer than 20000 characters. The job is async; poll with
                get_report_ai_job and reuse returned jobs when is_deduplicated=true.
                For complex or multi-condition reports, prefer narrower
                periods and simpler grouped requests; do not create duplicate
                queued jobs without user consent.
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
                After successful confirmation the job becomes existing_report_matched,
                and rows can be read with get_report_ai_job_data without saving a
                new report. recognized.preview_example_row is LLM-generated example
                preview metadata, not a verified live clinic row.
                If MCP observes the same job queued for 30+ seconds, the safe
                job payload includes mcp_queue_diagnostics with operator hints.
                Keep polling bounded. If a complex report remains queued, explain
                that processing is on the Vetmanager side and suggest checking
                later or simplifying/splitting the report intent.
        """
        payload = await _call_vm("GET", f"/rest/api/report-ai-job/{job_id}")
        return _annotate_report_ai_job_payload(payload)

    @mcp.tool
    async def confirm_report_ai_job_candidate(job_id: int, report_id: int) -> dict:
        """Confirm one existing report candidate for a Report AI job.

        Args:
            job_id: Report AI job ID currently in needs_confirmation.
            report_id: Candidate report ID from get_report_ai_job job.candidates.
                A successful confirmation makes the job existing_report_matched;
                call get_report_ai_job_data next when rows are needed.
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
                needed. Returned rows are capped by Vetmanager at 10000 and
                limited=true means total is larger. When limited=true or totals
                approach the cap, prefer narrowing the report or CSV/XLSX export
                via the returned csv_export_url/report_id for bulk review.
        """
        payload = await _call_vm("GET", f"/rest/api/report-ai-job/{job_id}/data")
        return _annotate_report_ai_data_payload(payload)

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
