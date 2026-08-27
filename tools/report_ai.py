"""Report AI job tools for Vetmanager report constructor workflows."""

import json
import time
from collections import OrderedDict
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from exceptions import AuthError, ToolInputError, VetmanagerError, reportable_error
from observability_logging import RUNTIME_LOGGER
from prompts import get_report_ai_prompt_helper_text
from tool_access_registry import SCOPE_DENIED_ERROR_CODE
from runtime_auth import get_current_runtime_credentials
from service_metrics import (
    instrument_call,
    record_report_ai_export,
    record_report_ai_export_duration,
    record_report_ai_job_created,
    record_report_ai_job_stage_duration,
    record_report_ai_job_terminal_outcome,
    record_report_ai_job_transition,
    record_report_ai_long_queued_poll,
    record_report_ai_stage_stall_poll,
)
from vetmanager_client import VetmanagerClient


INTENT_MAX_LENGTH = 20000
REPORT_AI_DATA_ROW_LIMIT = 10000
REPORT_AI_LARGE_RESULT_GUIDANCE_THRESHOLD = 9000
REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS = 30
REPORT_AI_QUEUE_WAIT_LIMIT_SECONDS = 15 * 60
REPORT_AI_EXPORT_WAIT_LIMIT_SECONDS = 30 * 60
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
_REPORT_AI_LIFECYCLE_OBSERVATIONS: OrderedDict[
    _ReportAiQueueObservationKey, dict[str, float | str]
] = OrderedDict()
_REPORT_AI_FINALIZED_OBSERVATIONS: OrderedDict[_ReportAiQueueObservationKey, float] = OrderedDict()
_REPORT_AI_EXPORT_OBSERVATIONS: OrderedDict[
    _ReportAiQueueObservationKey, dict[str, float | bool]
] = OrderedDict()
_REPORT_AI_CLINIC_TIMEZONES: OrderedDict[tuple[int | None, int | None, int], str] = OrderedDict()
_REPORT_AI_STAGE_BY_STATUS = {
    "queued": "queued",
    "recognizing": "recognized",
    "building_preview": "preview",
    "ready_to_save": "ready_to_save",
    "needs_confirmation": "needs_confirmation",
    "saved": "saved",
    "existing_report_matched": "existing_report_matched",
    "failed": "failed",
    "rejected": "rejected",
}
_REPORT_AI_TERMINAL_OUTCOMES = frozenset({
    "saved", "existing_report_matched", "failed", "rejected",
})
# Stage 252.3: stages where the service is supposed to be working. Waiting here
# past the limit is a hang; `needs_confirmation` waits for a person and
# `ready_to_save` waits for the caller, so neither belongs.
_REPORT_AI_ACTIVE_STAGE_STATUSES = ("recognizing", "building_preview")


def _monotonic_seconds() -> float:
    return time.monotonic()


def _unix_seconds() -> float:
    return time.time()


async def _upstream_job_age_seconds(job: dict) -> int | None:
    """Use clinic-local created_at only with a verified IANA clinic timezone."""
    created_at = job.get("created_at")
    clinic_id = job.get("clinic_id")
    key = _report_ai_queue_observation_key({"id": clinic_id})
    if not isinstance(created_at, str) or key is None:
        return None
    timezone_name = _REPORT_AI_CLINIC_TIMEZONES.get(key)
    if timezone_name is None:
        try:
            payload = await VetmanagerClient().get(f"/rest/api/clinics/{key[2]}")
        except VetmanagerError:
            RUNTIME_LOGGER.warning("report_ai_queue_age_timezone_unavailable", extra={"event_name": "report_ai_queue_age_timezone_unavailable"})
            return None
        data = payload.get("data") if isinstance(payload, dict) else None
        clinic = data.get("clinics") if isinstance(data, dict) else None
        if isinstance(clinic, list):
            clinic = clinic[0] if clinic else None
        timezone_name = clinic.get("time_zone") if isinstance(clinic, dict) else None
        if not isinstance(timezone_name, str) or not timezone_name:
            RUNTIME_LOGGER.warning("report_ai_queue_age_timezone_unavailable", extra={"event_name": "report_ai_queue_age_timezone_unavailable"})
            return None
        _REPORT_AI_CLINIC_TIMEZONES[key] = timezone_name
    try:
        created = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ZoneInfo(timezone_name))
    except (ValueError, ZoneInfoNotFoundError):
        return None
    return max(0, int(_unix_seconds() - created.timestamp()))


def _reset_report_ai_queue_observations() -> None:
    _REPORT_AI_QUEUE_OBSERVATIONS.clear()
    _REPORT_AI_LIFECYCLE_OBSERVATIONS.clear()
    _REPORT_AI_FINALIZED_OBSERVATIONS.clear()
    _REPORT_AI_EXPORT_OBSERVATIONS.clear()
    _REPORT_AI_CLINIC_TIMEZONES.clear()


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

    expired_lifecycle_keys = [
        key
        for key, observation in _REPORT_AI_LIFECYCLE_OBSERVATIONS.items()
        if now - float(observation["last_seen"]) > REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS
    ]
    for key in expired_lifecycle_keys:
        observation = _REPORT_AI_LIFECYCLE_OBSERVATIONS.pop(key)
        stage = str(observation["stage"])
        stage_duration = now - float(observation["stage_started"])
        record_report_ai_job_stage_duration(stage=stage, duration_seconds=stage_duration)
        record_report_ai_job_terminal_outcome(
            outcome="abandoned_wait",
            duration_seconds=now - float(observation["first_seen"]),
        )

    while len(_REPORT_AI_LIFECYCLE_OBSERVATIONS) > REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES:
        _, observation = _REPORT_AI_LIFECYCLE_OBSERVATIONS.popitem(last=False)
        record_report_ai_job_stage_duration(
            stage=str(observation["stage"]),
            duration_seconds=now - float(observation["stage_started"]),
        )
        record_report_ai_job_terminal_outcome(
            outcome="abandoned_wait",
            duration_seconds=now - float(observation["first_seen"]),
        )

    expired_finalized_keys = [
        key
        for key, last_seen in _REPORT_AI_FINALIZED_OBSERVATIONS.items()
        if now - last_seen > REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS
    ]
    for key in expired_finalized_keys:
        _REPORT_AI_FINALIZED_OBSERVATIONS.pop(key, None)
    while len(_REPORT_AI_FINALIZED_OBSERVATIONS) > REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES:
        _REPORT_AI_FINALIZED_OBSERVATIONS.popitem(last=False)

    expired_export_keys = [
        key
        for key, observation in _REPORT_AI_EXPORT_OBSERVATIONS.items()
        if now - float(observation["last_seen"])
        > REPORT_AI_QUEUE_OBSERVATION_TTL_SECONDS
    ]
    for key in expired_export_keys:
        observation = _REPORT_AI_EXPORT_OBSERVATIONS.pop(key)
        _record_abandoned_report_ai_export(observation, now=now)
    while len(_REPORT_AI_EXPORT_OBSERVATIONS) > REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES:
        _, observation = _REPORT_AI_EXPORT_OBSERVATIONS.popitem(last=False)
        _record_abandoned_report_ai_export(observation, now=now)


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


def _remember_report_ai_export(report_file_id: object) -> None:
    key = _report_ai_queue_observation_key({"id": report_file_id})
    if key is None:
        return
    now = _monotonic_seconds()
    _cleanup_report_ai_queue_observations(now)
    _REPORT_AI_EXPORT_OBSERVATIONS[key] = {
        "started_at": now,
        "last_seen": now,
        "has_polled": False,
    }
    _REPORT_AI_EXPORT_OBSERVATIONS.move_to_end(key)


def _record_abandoned_report_ai_export(
    observation: dict[str, float | bool], *, now: float
) -> None:
    operation = "poll" if observation["has_polled"] else "start"
    record_report_ai_export(operation=operation, outcome="abandoned_wait")
    record_report_ai_export_duration(
        outcome="abandoned_wait", duration_seconds=now - float(observation["started_at"])
    )


def _mark_report_ai_export_poll(report_file_id: object) -> None:
    key = _report_ai_queue_observation_key({"id": report_file_id})
    if key is None:
        return
    observation = _REPORT_AI_EXPORT_OBSERVATIONS.get(key)
    if observation is not None:
        observation["has_polled"] = True
        observation["last_seen"] = _monotonic_seconds()
        _REPORT_AI_EXPORT_OBSERVATIONS.move_to_end(key)


def _report_ai_export_observed_wait_seconds(report_file_id: object) -> int | None:
    key = _report_ai_queue_observation_key({"id": report_file_id})
    if key is None:
        return None
    observation = _REPORT_AI_EXPORT_OBSERVATIONS.get(key)
    if observation is None:
        return None
    return max(0, int(_monotonic_seconds() - float(observation["started_at"])))


def _complete_report_ai_export(report_file_id: object, *, outcome: str) -> None:
    key = _report_ai_queue_observation_key({"id": report_file_id})
    record_report_ai_export(operation="poll", outcome=outcome)
    if key is None:
        return
    observation = _REPORT_AI_EXPORT_OBSERVATIONS.pop(key, None)
    if observation is not None:
        record_report_ai_export_duration(
            outcome=outcome,
            duration_seconds=_monotonic_seconds() - float(observation["started_at"]),
        )


def _record_pending_report_ai_export_poll() -> None:
    """Count a retryable export-file poll without ending its observation."""
    record_report_ai_export(operation="poll", outcome="not_ready")


def _remember_finalized_report_ai_job(
    observation_key: _ReportAiQueueObservationKey, *, now: float
) -> None:
    """Keep a bounded, recently-finalized job key to deduplicate later polls."""
    _REPORT_AI_FINALIZED_OBSERVATIONS[observation_key] = now
    _REPORT_AI_FINALIZED_OBSERVATIONS.move_to_end(observation_key)
    while len(_REPORT_AI_FINALIZED_OBSERVATIONS) > REPORT_AI_QUEUE_OBSERVATION_MAX_ENTRIES:
        _REPORT_AI_FINALIZED_OBSERVATIONS.popitem(last=False)


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


def _report_ai_stage_age_seconds(job: dict, *, now: float) -> int | None:
    """How long this job has been sitting in its current stage (stage 252.3).

    Read from the lifecycle observation, which already tracks when each stage
    started — a second counter would only have to be kept in sync with it.
    A stage change resets the clock on purpose: movement is not a hang.
    """
    observation_key = _report_ai_queue_observation_key(job)
    if observation_key is None:
        return None
    observation = _REPORT_AI_LIFECYCLE_OBSERVATIONS.get(observation_key)
    if observation is None:
        return None
    stage = _REPORT_AI_STAGE_BY_STATUS.get(str(job.get("status") or ""), "unknown")
    if str(observation["stage"]) != stage:
        return None
    return max(0, int(now - float(observation["stage_started"])))


def _observe_report_ai_lifecycle(job: dict, *, now: float | None = None) -> None:
    """Record safe, process-local lifecycle observations for one Report AI job."""
    observation_key = _report_ai_queue_observation_key(job)
    if observation_key is None:
        return
    current_time = _monotonic_seconds() if now is None else now
    _cleanup_report_ai_queue_observations(current_time)
    if observation_key in _REPORT_AI_FINALIZED_OBSERVATIONS:
        _remember_finalized_report_ai_job(observation_key, now=current_time)
        return
    stage = _REPORT_AI_STAGE_BY_STATUS.get(str(job.get("status") or ""), "unknown")
    observation = _REPORT_AI_LIFECYCLE_OBSERVATIONS.get(observation_key)
    if observation is None:
        if stage in _REPORT_AI_TERMINAL_OUTCOMES:
            record_report_ai_job_stage_duration(stage=stage, duration_seconds=0.0)
            record_report_ai_job_terminal_outcome(outcome=stage, duration_seconds=0.0)
            _remember_finalized_report_ai_job(observation_key, now=current_time)
            return
        _REPORT_AI_LIFECYCLE_OBSERVATIONS[observation_key] = {
            "first_seen": current_time,
            "last_seen": current_time,
            "stage": stage,
            "stage_started": current_time,
        }
        return

    previous_stage = str(observation["stage"])
    observation["last_seen"] = current_time
    _REPORT_AI_LIFECYCLE_OBSERVATIONS.move_to_end(observation_key)
    if stage == previous_stage:
        return

    record_report_ai_job_stage_duration(
        stage=previous_stage,
        duration_seconds=current_time - float(observation["stage_started"]),
    )
    record_report_ai_job_transition(from_stage=previous_stage, to_stage=stage)
    if stage in _REPORT_AI_TERMINAL_OUTCOMES:
        record_report_ai_job_stage_duration(stage=stage, duration_seconds=0.0)
        record_report_ai_job_terminal_outcome(
            outcome=stage, duration_seconds=current_time - float(observation["first_seen"])
        )
        _REPORT_AI_LIFECYCLE_OBSERVATIONS.pop(observation_key, None)
        _remember_finalized_report_ai_job(observation_key, now=current_time)
        return
    observation["stage"] = stage
    observation["stage_started"] = current_time


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


async def _annotate_report_ai_queue_diagnostics(payload: dict, *, now: float | None = None) -> dict:
    data = payload.get("data")
    job = data.get("job") if isinstance(data, dict) else payload.get("job")
    if not isinstance(job, dict):
        return payload

    status = str(job.get("status") or "")
    # The queue answers "how long until this starts"; an active stage answers
    # "how long has this stage stopped moving". Mixing them would hand a job
    # that merely queued for an hour an instant wait-limit on its first second
    # of recognising.
    if status == "queued":
        observed_age_seconds = _observe_report_ai_queue(job, now=now)
        upstream_age_seconds = await _upstream_job_age_seconds(job)
        diagnostic_age_seconds = (
            upstream_age_seconds if upstream_age_seconds is not None else observed_age_seconds
        )
        age_scope = "job"
        age_source = "upstream_created_at" if upstream_age_seconds is not None else "mcp_observed"
    elif status in _REPORT_AI_ACTIVE_STAGE_STATUSES:
        _observe_report_ai_queue(job, now=now)  # clears any stale queue observation
        diagnostic_age_seconds = _report_ai_stage_age_seconds(job, now=now or _monotonic_seconds())
        age_scope = "stage"
        age_source = "mcp_observed"
    else:
        _observe_report_ai_queue(job, now=now)
        return payload

    if (
        diagnostic_age_seconds is None
        or diagnostic_age_seconds < REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS
    ):
        return payload

    at_wait_limit = diagnostic_age_seconds >= REPORT_AI_QUEUE_WAIT_LIMIT_SECONDS
    diagnostics = {
        "code": "report_ai_job_wait_limit_reached" if at_wait_limit else "report_ai_job_long_queued",
        "observed_age_seconds": diagnostic_age_seconds,
        "age_scope": age_scope,
        "threshold_seconds": REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS,
        "status": status,
        "operator_hint": (
            "Age comes from Vetmanager created_at when available, otherwise MCP local observation; "
            "it is not a Vetmanager worker SLA. "
            "Inspect Report AI worker/stale in-progress diagnostics using the MCP operator runbook."
        ),
    }
    if age_scope == "job":
        # Kept for callers that already read the queue-specific field.
        diagnostics["observed_queued_age_seconds"] = diagnostic_age_seconds
    diagnostics["age_source"] = age_source
    for field_name in ("created_at", "updated_at"):
        if job.get(field_name):
            diagnostics[field_name] = job[field_name]
    if at_wait_limit:
        already_started = age_scope == "stage"
        diagnostics.update({
            "stop_automatic_polling": True,
            "next_step": (
                "Do not create a duplicate job. "
                + (
                    "This job already started working, so re-running it only doubles the queue; "
                    if already_started
                    else "The same job may still finish upstream; "
                )
                + "re-check this same job_id later. For invoice KPI only, a last-resort fallback "
                "is get_invoices with full pagination: compare returned rows to totalCount before "
                "summing amount by doctor_id."
            ),
        })

    job.setdefault("mcp_queue_diagnostics", diagnostics)
    # The queue counter keeps meaning "waiting to start"; a stalled working
    # stage is a different question and gets its own counter.
    if age_scope == "job":
        record_report_ai_long_queued_poll()
    else:
        record_report_ai_stage_stall_poll()
    # The log contract is split the same way the metric is: an external alert
    # on `report_ai_job_long_queued` was written to mean the queue, and a
    # stalled working stage is a different failure. The queue keeps its event
    # name and its `observed_queued_age_seconds`; the stage gets its own.
    if age_scope == "job":
        event_name = "report_ai_job_long_queued"
        age_field = "observed_queued_age_seconds"
        bucket_field = "observed_queued_age_bucket"
    else:
        event_name = "report_ai_job_stage_stalled"
        age_field = "observed_stage_age_seconds"
        bucket_field = "observed_stage_age_bucket"
    RUNTIME_LOGGER.warning(
        event_name,
        extra={
            "event_name": event_name,
            "status": status,
            "age_scope": age_scope,
            "threshold_seconds": REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS,
            age_field: diagnostic_age_seconds,
            bucket_field: _queued_age_bucket(diagnostic_age_seconds),
            "age_source": age_source,
            "wait_limit_reached": at_wait_limit,
        },
    )
    return payload


async def _annotate_report_ai_job_payload(payload: dict) -> dict:
    observed_at = _monotonic_seconds()
    annotated = _annotate_report_ai_workarounds(payload)
    # Stage 252.3: the lifecycle observation is updated first — the diagnostics
    # read the current stage's clock from it, and on the first poll of a new
    # stage a stale observation would still hold the previous stage's time.
    job = _extract_job(annotated)
    if job:
        _observe_report_ai_lifecycle(job, now=observed_at)
    return await _annotate_report_ai_queue_diagnostics(annotated, now=observed_at)


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
        raise ToolInputError("intent_text must be non-empty.")
    if len(intent) > INTENT_MAX_LENGTH:
        raise ToolInputError(f"intent_text must be no longer than {INTENT_MAX_LENGTH} characters.")
    return intent


def _validate_report_title(title: str) -> str:
    value = (title or "").strip()
    if len(value) < 12 or value.lower() in _GENERIC_REPORT_TITLES:
        raise ToolInputError(
            "title must be meaningful: include the report purpose and period when applicable."
        )
    return value


def _tool_error_from_vm(exc: VetmanagerError) -> ToolError:
    return reportable_error(str(exc))


def _validate_positive_int(name: str, value: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ToolInputError(f"{name} must be a positive integer.") from None
    if number <= 0:
        raise ToolInputError(f"{name} must be a positive integer.")
    return number


def _upstream_positive_int(name: str, value) -> int:
    """Same check, but the value came from Vetmanager, not from the caller.

    Stage 265.6: `_validate_positive_int` now blames the caller by type. Run it
    on a payload field and a broken upstream answer would be reported as the
    agent's own typo.
    """
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = 0
    if number <= 0:
        raise reportable_error(
            f"Report AI job carries an unusable {name}; this job cannot be exported."
        )
    return number


def _report_filter_params(report_id: int, filter_json: str | None = None) -> dict[str, str | int]:
    params: dict[str, str | int] = {"report_id": _validate_positive_int("report_id", report_id)}
    filter_value = (filter_json or "").strip()
    if not filter_value:
        return params
    try:
        json.loads(filter_value)
    except json.JSONDecodeError as exc:
        raise ToolInputError("filter_json must be valid JSON when provided.") from exc
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
        raise reportable_error("Starting report export failed.")
    report = _extract_report(payload)
    if not report.get("report_file_id"):
        raise reportable_error("Starting report export failed: report_file_id is missing.")
    return payload


def _ensure_report_file_payload(payload: dict) -> dict:
    if payload.get("success") is False:
        raise reportable_error("Getting report export file failed.")
    report = _extract_report(payload)
    if not any(
        report.get(name)
        for name in ("html_file", "csv_file", "csv_semicolon_file", "xlsx_file")
    ):
        raise reportable_error("Getting report export file failed: export file fields are missing.")
    return payload


def _safe_export_error(
    exc: VetmanagerError,
    action: str,
    *,
    retry_on_conflict: bool = False,
    report_id_from_caller: bool = False,
) -> ToolError:
    if isinstance(exc, AuthError) and exc.error_code == SCOPE_DENIED_ERROR_CODE:
        return _tool_error_from_vm(exc)
    status = f" HTTP {exc.status_code}" if exc.status_code is not None else ""
    code = f" ({exc.error_code})" if exc.error_code else ""
    lowered = str(exc).lower()
    if retry_on_conflict and _is_retryable_export_file_error(exc):
        return reportable_error(
            "Report export is not ready yet; call get_report_export_file again after a delay."
        )
    if exc.status_code == 403:
        if "report creating in progress" in lowered:
            return reportable_error(
                "Report export is temporarily blocked by Vetmanager's tenant-wide REST export guard; "
                "wait 30 minutes before one new StartReport attempt. Do not retry "
                "automatically, immediately, or in parallel."
            )
        if "can not run a report more than 10 minutes" in lowered:
            return reportable_error(
                "Report export is temporarily limited by Vetmanager's tenant-wide REST export guard; "
                "wait 30 minutes before one new StartReport attempt. Do not retry "
                "automatically, immediately, or in parallel."
            )
        if "not accessible for rest" in lowered:
            message = (
                "Report is not REST-exportable: Vetmanager denied StartReport for this report_id."
            )
            # Stage 265.6: when the caller chose the report_id, this is a
            # precondition its own docstring states, not a defect. Sentry issue
            # PYTHON-N is exactly this refusal, filed against us.
            if report_id_from_caller:
                return ToolInputError(message)
            return reportable_error(message)
        return reportable_error(
            "Report export was denied or temporarily limited by Vetmanager (HTTP 403). "
            "Retry only with bounded attempts; if it keeps failing, treat this report_id "
            "as not currently exportable."
        )
    return reportable_error(f"{action} failed{status}{code}.")


def _is_retryable_export_file_error(exc: VetmanagerError) -> bool:
    """Return the single retryable classification shared by tool and metrics."""
    lowered = str(exc).lower()
    return exc.status_code in {401, 409} and (
        exc.status_code == 409
        or "build in progress" in lowered
        or "not started" in lowered
    )


async def _call_vm(
    method: str,
    path: str,
    *,
    json: dict | None = None,
    params: dict | None = None,
    tool_name: str,
    metric_endpoint: str,
) -> dict:
    client = VetmanagerClient()

    async def request() -> dict:
        if method == "GET":
            return await client.get(path, params=params)
        if method == "POST":
            return await client.post(path, json=json or {})
        raise RuntimeError(f"Unsupported Report AI method: {method}")

    try:
        return await instrument_call(
            metric_endpoint, method, request, tool_name=tool_name
        )
    except VetmanagerError as exc:
        raise _tool_error_from_vm(exc) from None


async def _start_report_export(
    report_id: int,
    filter_json: str | None = None,
    *,
    tool_name: str,
    report_id_from_caller: bool = False,
) -> dict:
    params = _report_filter_params(report_id, filter_json)
    client = VetmanagerClient()
    try:
        payload = await instrument_call(
            "/rest/api/report/StartReport",
            "GET",
            lambda: client.get("/rest/api/report/StartReport", params=params, retry=False),
            tool_name=tool_name,
        )
        payload = _ensure_start_report_payload(payload)
        report_file_id = _extract_report(payload).get("report_file_id")
        record_report_ai_export(operation="start", outcome="success")
        _remember_report_ai_export(report_file_id)
        return payload
    except VetmanagerError as exc:
        record_report_ai_export(operation="start", outcome="error")
        raise _safe_export_error(
            exc, "Starting report export", report_id_from_caller=report_id_from_caller,
        ) from None
    except ToolError:
        record_report_ai_export(operation="start", outcome="error")
        raise


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
        try:
            intent = _validate_intent_text(intent_text)
            payload = await _call_vm(
                "POST", "/rest/api/report-ai-job", json={"intent_text": intent},
                tool_name="create_report_ai_job",
                metric_endpoint="/rest/api/report-ai-job",
            )
        except Exception:
            record_report_ai_job_created(outcome="error")
            raise
        record_report_ai_job_created(outcome="success")
        job = _extract_job(payload)
        _observe_report_ai_lifecycle(job)
        _observe_report_ai_queue(job)
        return payload

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
                new report. recognized.preview_example_row contains deliberately
                invented example values, not clinic data; use its columns and
                value types only to check the expected table structure, and
                never repeat its values to the user.
                If a job stops moving for 30+ seconds, the safe job payload
                includes mcp_queue_diagnostics. It covers the queue and the
                working stages alike: age_scope says whether the age measures
                the whole job (queued) or the current stage (recognizing,
                building_preview), and a stage change restarts that clock.
                The age is process-local, not a Vetmanager SLA. At 15 minutes
                stop automatic polling and do not create a duplicate: the same
                job may still finish, and on a working stage a duplicate only
                doubles the queue. Re-check the same job later. Invoice KPI
                fallback needs complete get_invoices pagination before summing amount
                by doctor_id; it is not a direct aggregate.
        """
        payload = await _call_vm(
            "GET", f"/rest/api/report-ai-job/{job_id}", tool_name="get_report_ai_job",
            metric_endpoint="/rest/api/report-ai-job/{id}",
        )
        return await _annotate_report_ai_job_payload(payload)

    @mcp.tool
    async def confirm_report_ai_job_candidate(job_id: int, report_id: int) -> dict:
        """Confirm one existing report candidate for a Report AI job.

        Args:
            job_id: Report AI job ID currently in needs_confirmation.
            report_id: Candidate report ID from get_report_ai_job job.candidates.
                A successful confirmation makes the job existing_report_matched;
                call get_report_ai_job_data next when rows are needed.
        """
        payload = await _call_vm(
            "POST",
            f"/rest/api/report-ai-job/{job_id}/confirm",
            json={"report_id": report_id},
            tool_name="confirm_report_ai_job_candidate",
            metric_endpoint="/rest/api/report-ai-job/{id}/confirm",
        )
        _observe_report_ai_lifecycle(_extract_job(payload))
        return payload

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
        payload = await _call_vm(
            "GET", f"/rest/api/report-ai-job/{job_id}/data", tool_name="get_report_ai_job_data",
            metric_endpoint="/rest/api/report-ai-job/{id}/data",
        )
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
        payload = await _call_vm(
            "POST",
            f"/rest/api/report-ai-job/{job_id}/save",
            json={"title": safe_title},
            tool_name="save_report_ai_job_as_report",
            metric_endpoint="/rest/api/report-ai-job/{id}/save",
        )
        _observe_report_ai_lifecycle(_extract_job(payload))
        return payload

    @mcp.tool
    async def start_report_export(report_id: int, filter_json: str | None = None) -> dict:
        """Start Vetmanager Report Constructor CSV/XLSX export for a known report ID.

        Args:
            report_id: Existing Report Constructor report ID with REST export enabled.
            filter_json: Optional report-specific JSON filter. Omitted when empty;
                MCP validates JSON syntax only, not report-specific semantics.
        """
        return await _start_report_export(
            report_id,
            filter_json,
            tool_name="start_report_export",
            report_id_from_caller=True,
        )

    @mcp.tool
    async def get_report_export_file(report_file_id: int) -> dict:
        """Get CSV/XLSX export file locators after start_report_export.

        Args:
            report_file_id: Export build ID returned by start_report_export.
                If Vetmanager says generation is still in progress, retry this
                tool after a delay.
        """
        file_id = _validate_positive_int("report_file_id", report_file_id)
        _mark_report_ai_export_poll(file_id)
        client = VetmanagerClient()
        try:
            payload = await instrument_call(
                "/rest/api/report/reportFile",
                "GET",
                lambda: client.get("/rest/api/report/reportFile", params={"file_id": file_id}),
                tool_name="get_report_export_file",
            )
            payload = _ensure_report_file_payload(payload)
            _complete_report_ai_export(file_id, outcome="success")
            return payload
        except VetmanagerError as exc:
            if _is_retryable_export_file_error(exc):
                observed_wait = _report_ai_export_observed_wait_seconds(file_id)
                if (
                    observed_wait is not None
                    and observed_wait >= REPORT_AI_EXPORT_WAIT_LIMIT_SECONDS
                ):
                    record_report_ai_export(operation="poll", outcome="wait_limit_reached")
                    RUNTIME_LOGGER.warning(
                        "report_ai_export_wait_limit_reached",
                        extra={
                            "event_name": "report_ai_export_wait_limit_reached",
                            "observed_wait_seconds": observed_wait,
                            "wait_limit_seconds": REPORT_AI_EXPORT_WAIT_LIMIT_SECONDS,
                        },
                    )
                    raise reportable_error(
                        "MCP observed this export still not ready for 30 minutes. Stop automatic "
                        "polling and do not start a new export: this same build may still finish. "
                        "You may re-check this same report_file_id later; only choose a narrower "
                        "selection after deciding the existing build is no longer needed."
                    ) from None
                _record_pending_report_ai_export_poll()
            else:
                _complete_report_ai_export(file_id, outcome="error")
            raise _safe_export_error(
                exc, "Getting report export file", retry_on_conflict=True
            ) from None
        except ToolError:
            _complete_report_ai_export(file_id, outcome="error")
            raise

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
        job_payload = await _call_vm(
            "GET", f"/rest/api/report-ai-job/{safe_job_id}",
            tool_name="get_report_ai_job_export",
            metric_endpoint="/rest/api/report-ai-job/{id}",
        )
        job = _extract_job(job_payload)
        status = str(job.get("status") or "")
        if status not in {"saved", "existing_report_matched"}:
            raise ToolInputError(
                "Report AI job must be saved or existing_report_matched before export."
            )
        report_id = job.get("report_id")
        if not report_id:
            raise reportable_error("Report AI job does not include report_id for export.")
        safe_report_id = _upstream_positive_int("report_id", report_id)
        return await _start_report_export(
            safe_report_id, filter_json, tool_name="get_report_ai_job_export"
        )
