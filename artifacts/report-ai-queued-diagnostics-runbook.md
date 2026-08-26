# Report AI wait diagnostics runbook — 2026-06-18, extended 2026-08-26

## Signal

`get_report_ai_job` adds `data.job.mcp_queue_diagnostics` when a Report AI job stops moving for at least 30 monotonic seconds.

Stage 252.3 extended this beyond the queue. Two different questions are answered under the same block, and `age_scope` says which one:

- `age_scope=job` — status `queued`: how long the job has been waiting to start. Age comes from upstream `created_at` when the clinic timezone is known, otherwise from local observation.
- `age_scope=stage` — status `recognizing` or `building_preview`: how long the **current stage** has stopped moving. A stage change restarts this clock, because movement is not a hang.

`needs_confirmation` and `ready_to_save` never produce the block: there the job waits for a person or for the caller, not for a worker.

The signal is MCP-side and process-local. In multi-worker deployments, polls routed to different workers can under-count observed age. Treat the metric/log as a symptom that users are seeing long queued states, not as authoritative upstream queue duration.

## Safe fields

The diagnostic block may include:

- `code=report_ai_job_long_queued` or `code=report_ai_job_wait_limit_reached`
- `observed_age_seconds` and `age_scope` (`job` or `stage`)
- `observed_queued_age_seconds` — queue only, kept for callers that already read it
- `threshold_seconds`
- `status` — the job's actual status, not always `queued`
- `stop_automatic_polling` and `next_step`, once the wait limit is reached
- upstream `created_at` / `updated_at`, if present
- `operator_hint`

It must not include `intent_text`, raw SQL, recognized structure, candidates, client data, clinic domain, or API secrets.

## Operator checks

1. Ask the agent/user to continue bounded polling rather than waiting inside one call.
2. Check MCP runtime logs. The two failures have separate event names, so an alert written for one never fires on the other: `event_name=report_ai_job_long_queued` with `observed_queued_age_seconds` for the queue, `event_name=report_ai_job_stage_stalled` with `observed_stage_age_seconds` for a stalled working stage. Both carry `age_scope`. The counters are separate too, and deliberately so: `vetmanager_report_ai_long_queued_polls_total` still means "jobs waiting to start", while `vetmanager_report_ai_stage_stall_polls_total` counts polls where a working stage stopped moving. A rise in the second one, with the first flat, means jobs start and then die mid-work — a different upstream problem than a backed-up queue.
3. If the signal persists, inspect upstream Report AI worker/queue health and stale in-progress cleanup outside MCP.
4. Use upstream job timestamps only as context. Do not calculate a 30-second threshold from naive Vetmanager timestamps unless the server timezone is explicitly known.
5. If the job eventually moves out of `queued`, MCP clears the local queue observation for that job; the stage clock restarts on every stage change.
6. At the wait limit (15 minutes) the diagnostics tell the caller to stop automatic polling and not to create a duplicate job. On a working stage the wording is stronger — the job already started, so a duplicate only doubles the queue.
