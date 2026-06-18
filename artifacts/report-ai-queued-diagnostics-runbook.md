# Report AI queued diagnostics runbook — 2026-06-18

## Signal

`get_report_ai_job` adds `data.job.mcp_queue_diagnostics` when this MCP process has observed the same Report AI job in `queued` for at least 30 monotonic seconds.

The signal is MCP-side and process-local. In multi-worker deployments, polls routed to different workers can under-count observed age. Treat the metric/log as a symptom that users are seeing long queued states, not as authoritative upstream queue duration.

## Safe fields

The diagnostic block may include:

- `code=report_ai_job_long_queued`
- `observed_queued_age_seconds`
- `threshold_seconds`
- `status`
- upstream `created_at` / `updated_at`, if present
- `operator_hint`

It must not include `intent_text`, raw SQL, recognized structure, candidates, client data, clinic domain, or API secrets.

## Operator checks

1. Ask the agent/user to continue bounded polling rather than waiting inside one call.
2. Check MCP runtime logs for `event_name=report_ai_job_long_queued` and compare with `vetmanager_report_ai_long_queued_polls_total`.
3. If the signal persists, inspect upstream Report AI worker/queue health and stale in-progress cleanup outside MCP.
4. Use upstream job timestamps only as context. Do not calculate a 30-second threshold from naive Vetmanager timestamps unless the server timezone is explicitly known.
5. If the job eventually moves out of `queued`, MCP clears the local observation state for that job.
