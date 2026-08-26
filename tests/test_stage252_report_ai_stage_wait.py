"""Stage 252.3: a Report AI job has an end to waiting on every stage, not just the queue.

Feedback report 48 (25.08.2026) came from a working account whose job sat in
`recognizing` across repeated status checks. The queue had a wait limit and a
"stop polling" hint; every stage after it had neither, so the model polled
until it gave up.
"""

from __future__ import annotations

import pytest

import tools.report_ai as report_ai


def _annotate(job: dict):
    return report_ai._annotate_report_ai_job_payload({"data": {"job": job}})


def _diagnostics(result: dict) -> dict | None:
    return result["data"]["job"].get("mcp_queue_diagnostics")


@pytest.fixture(autouse=True)
def _clean_observations():
    report_ai._reset_report_ai_queue_observations()
    yield
    report_ai._reset_report_ai_queue_observations()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["recognizing", "building_preview"])
async def test_stuck_active_stage_gets_diagnostics_naming_its_own_status(monkeypatch, status):
    """The stage that is stuck must be the stage the diagnostics talk about."""
    job = {"id": 501, "status": status}
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    assert _diagnostics(await _annotate(job)) is None

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS + 1),
    )
    diagnostics = _diagnostics(await _annotate(job))

    assert diagnostics is not None
    assert diagnostics["status"] == status
    assert diagnostics["age_scope"] == "stage"
    assert diagnostics["observed_age_seconds"] >= report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS
    # The queue-specific field belongs to the queue only.
    assert "observed_queued_age_seconds" not in diagnostics


@pytest.mark.asyncio
async def test_active_stage_at_wait_limit_stops_polling_without_a_duplicate(monkeypatch):
    """Re-running the job is the wrong move: the work has already started."""
    job = {"id": 502, "status": "recognizing"}
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    await _annotate(job)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_QUEUE_WAIT_LIMIT_SECONDS),
    )
    diagnostics = _diagnostics(await _annotate(job))

    assert diagnostics["code"] == "report_ai_job_wait_limit_reached"
    assert diagnostics["stop_automatic_polling"] is True
    assert "Do not create a duplicate" in diagnostics["next_step"]


@pytest.mark.asyncio
async def test_moving_to_a_new_stage_restarts_the_clock(monkeypatch):
    """A long queue must not condemn the stage that follows it.

    The job below waits out the whole limit in the queue and then starts
    recognizing. That first recognizing poll is progress, not a hang.
    """
    job = {"id": 503, "status": "queued"}
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    await _annotate(job)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_QUEUE_WAIT_LIMIT_SECONDS + 60),
    )
    assert _diagnostics(await _annotate(job))["code"] == "report_ai_job_wait_limit_reached"

    job = {"id": 503, "status": "recognizing"}
    assert _diagnostics(await _annotate(job)) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status", ["needs_confirmation", "ready_to_save", "saved", "failed", "rejected"]
)
async def test_stages_that_are_not_hanging_get_no_diagnostics(monkeypatch, status):
    """Waiting for a person, or being finished, is not a hang."""
    job = {"id": 504, "status": status}
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    await _annotate(job)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_QUEUE_WAIT_LIMIT_SECONDS * 2),
    )
    assert _diagnostics(await _annotate(job)) is None


@pytest.mark.asyncio
async def test_queued_keeps_its_own_contract(monkeypatch):
    """The queue answers "how long until it starts" and keeps its old field."""
    job = {"id": 505, "status": "queued"}
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    await _annotate(job)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS + 1),
    )
    diagnostics = _diagnostics(await _annotate(job))

    assert diagnostics["status"] == "queued"
    assert diagnostics["age_scope"] == "job"
    assert diagnostics["observed_queued_age_seconds"] >= report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS
    assert diagnostics["observed_age_seconds"] == diagnostics["observed_queued_age_seconds"]


@pytest.mark.asyncio
async def test_stage_stall_and_queue_wait_are_counted_apart(monkeypatch):
    """The queue counter feeds dashboards meaning "waiting to start" — keep it that way."""
    import service_metrics

    service_metrics.reset_service_metrics()
    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    queued = {"id": 601, "status": "queued"}
    stalled = {"id": 602, "status": "recognizing"}
    await _annotate(queued)
    await _annotate(stalled)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS + 1),
    )
    await _annotate(queued)
    await _annotate(stalled)

    snapshot = service_metrics.snapshot_service_metrics()
    assert snapshot["report_ai_long_queued_polls_total"] == 1
    assert snapshot["report_ai_stage_stall_polls_total"] == 1
    rendered = service_metrics.render_prometheus_metrics()
    assert "vetmanager_report_ai_stage_stall_polls_total 1" in rendered
    assert "vetmanager_report_ai_long_queued_polls_total 1" in rendered


def test_public_tool_description_covers_working_stages():
    """The description in the live schema, not just the docstring, must say it."""
    from tool_descriptions import SPECIAL_TOOL_DESCRIPTIONS

    description = SPECIAL_TOOL_DESCRIPTIONS["get_report_ai_job"]
    assert "recognizing/building_preview" in description
    assert "age_scope" in description


@pytest.mark.asyncio
async def test_log_event_names_are_split_like_the_metrics(monkeypatch, caplog):
    """An alert written for the queue must not start firing on stalled stages."""
    import logging

    monkeypatch.setattr(report_ai, "_monotonic_seconds", lambda: 0.0)
    queued = {"id": 701, "status": "queued"}
    stalled = {"id": 702, "status": "building_preview"}
    await _annotate(queued)
    await _annotate(stalled)

    monkeypatch.setattr(
        report_ai,
        "_monotonic_seconds",
        lambda: float(report_ai.REPORT_AI_LONG_QUEUED_THRESHOLD_SECONDS + 1),
    )
    with caplog.at_level(logging.WARNING, logger="vetmanager.runtime"):
        await _annotate(queued)
        await _annotate(stalled)

    events = {
        getattr(record, "event_name"): record
        for record in caplog.records
        if hasattr(record, "event_name")
    }
    assert "report_ai_job_long_queued" in events
    assert "report_ai_job_stage_stalled" in events

    queue_record = events["report_ai_job_long_queued"]
    assert queue_record.age_scope == "job"
    assert hasattr(queue_record, "observed_queued_age_seconds")

    stage_record = events["report_ai_job_stage_stalled"]
    assert stage_record.age_scope == "stage"
    assert stage_record.status == "building_preview"
    assert hasattr(stage_record, "observed_stage_age_seconds")
    assert not hasattr(stage_record, "observed_queued_age_seconds")
