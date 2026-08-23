# Этап 252. Задания Report AI зависают в очереди

## Цель

Сделать долгую очередь Report AI наблюдаемой и конечной для модели: после
bounded polling вернуть безопасную диагностику и проверенный обходной путь,
не заявляя, что MCP управляет worker Vetmanager.

## Воспроизведение и факты

- 24.08.2026 devtr6 smoke и специальный all-time medical-card intent не
  воспроизвели #37: job перешёл `queued → recognizing → ready_to_save` менее
  чем за 30 секунд.
- Local event `report_ai_job_long_queued` доказан unit regression, но он
  возникает только при `get_report_ai_job`, когда тот же process уже видел
  *queued* job 30+ секунд. `create_report_ai_job` не emits it, transitions to
  `recognizing` do not qualify, counters are process-local and reset on restart.
  Поэтому production zero не различает no calls, no repeated queued polls,
  restart, либо missing log ingestion.
- #37 workaround remains technically viable on devtr6: invoices are paginated
  and expose `doctor_id` and `amount` (100 of 114 rows on first page). It is
  not a direct aggregate and may be expensive for large periods.
- OpenAPI has no aggregate-by-doctor endpoint. A direct aggregate helper merits
  a separate Roadmap item; it is not folded into queue handling.

## Архитектурное решение

### Варианты

1. Retry/create duplicate jobs automatically — may multiply worker load and
   lose deduplication.
2. Promise upstream cleanup timing — no public API TTL/retry metadata exists.
3. Keep raw upstream status, augment local diagnostics at a bounded observed
   age, and tell the model to stop *automatic* polling but re-check the same
   job later; fallback requires complete pagination before arithmetic.
4. Derive age from upstream timestamps. Rejected: timestamps are untrusted
   public formatting and current diagnostic already intentionally measures
   MCP-observed age; persistent/shared state is out of scope.

Выбран вариант 3 with 15-minute local cap. It is MCP-observed, process-local
and not an upstream SLA; later `get_report_ai_job` keeps returning actual
upstream state. It is advisory-only across workers/sessions. The fallback
explicitly exposes raw financial rows to the caller, requires `totalCount`
versus returned count and full pagination before summing; therefore it is a
last resort, not an aggregate tool.

### Инварианты и rollback

- Queue worker ownership stays with Vetmanager; no cancellation/retry endpoint
  is invented.
- `queued` remains upstream payload status; diagnostic fields are additive.
- IDs, rows, intents and credentials never enter logs/metrics; direct-list
  fallback may return its normal authorised raw rows to the MCP caller.
- If a stable upstream job deadline becomes available, replace local wording
  with verified metadata and retain no duplicate retry.

Architecture Critique: required — public MCP contract and async reliability.

## Декомпозиция

1. Seed local observation on create and make early warning/15-minute guidance
   explicit process-local signals; deployment topology remains a limitation.
2. Extend diagnostics and tool descriptions with bounded stop and list-based
   grouped-invoice fallback.
3. Add mock regressions for state transition, cap and observation reset.

## Acceptance criteria

1. A queued job at 15 minutes exposes `stop_automatic_polling`, tells the
   caller the same job may finish later, and never advises a duplicate job.
2. The 30-second signal remains an early warning, distinct from terminal local
   wait and preserved across status semantics.
3. Payload and description explicitly contain threshold, process-local scope,
   no worker control, same-job re-check and no-duplicate guidance; regressions
   assert those fields/text.
4. A separate Roadmap item proposes direct invoice aggregates with rationale;
   it is not implemented in this stage.

## Review findings

Architecture Critique Claude Opus attempt 1/3: accepted the need for a defined
cap/re-check path, complete-pagination warning, advisory-only topology limit,
explicit fallback data exposure and verifiable wording. The timestamp-only
alternative is rejected because it would create an unverified upstream contract.
Evidence: `/tmp/vetmanager-mcp-review-evidence/2026-08-23T215458Z-file-PRD_-252--report-ai---_md-attempt-1-of-3.mNvUGl/claude-review-attempt-1-of-3.envelope.json`.
