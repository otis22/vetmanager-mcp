# Report AI MCP research — 2026-06-15

## Summary

`report-ai-job` in Vetmanager is an async AI report-constructor workflow:

1. `POST /rest/api/report-ai-job` creates a job from `intent_text`.
2. Background processing moves the job through recognition/build-preview states.
3. `GET /rest/api/report-ai-job/{id}` returns a safe job view without raw SQL.
4. `GET /rest/api/report-ai-job/{id}/data` returns table rows only when the job has a saved or matched report.
5. `POST /rest/api/report-ai-job/{id}/save` creates a persistent `report_constructor_reports` record.

The short prompt helper should be exposed to agents as prompt/resource guidance, not embedded into every tool call.

## Sources

- Prompt helpers:
  - `/home/otis/.var/app/org.telegram.desktop/data/TelegramDesktop/tdata/temp_data/ai-reports-client-prompt-short.md`
  - `/home/otis/.var/app/org.telegram.desktop/data/TelegramDesktop/tdata/temp_data/ai-reports-client-prompt-full.md`
- Vetmanager source of truth:
  - `/home/otis/myprojects/vetmanager-extjs/rest/protected/controllers/ReportAiJobsController.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/Job/JobService.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/Job/ReportAiJob.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/Job/JobStatus.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/AiReportFacade.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/AiReportRenderer.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/PromptBuilder.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/SchemaProvider.php`
  - `/home/otis/myprojects/vetmanager-extjs/application/src/Components/ReportConstructor/AI/PiiFieldsRegistry.php`

## Verified on devtr6

### Preview-only job

Intent:

```text
Покажи количество выполненных счетов за май 2026 года. Без персональных данных.
```

Observed:

- `POST /rest/api/report-ai-job` -> job `#2`, `queued`.
- Polling `GET /rest/api/report-ai-job/2` -> `ready_to_save`.
- Safe recognized:
  - description: `Количество выполненных счетов за май 2026 года`
  - tables: `["Счета"]`
  - fields: `["Счета → Количество"]`
  - filters: `["Статус счета = выполнен", "Дата счета в мае 2026"]`
  - period: `май 2026`
- `preview_summary`: `Превью: 1 строк, 1 колонок`.
- `GET /rest/api/report-ai-job/2/data` before save -> `409 INVALID_TRANSITION`.

### Full save/data path

After explicit user approval:

- `POST /rest/api/report-ai-job/2/save` -> `report_id=84`.
- `GET /rest/api/report-ai-job/2/data` -> columns `["Количество"]`, rows `[{"Количество": 0}]`.

Debtors test:

Intent requested clients with negative balance and no personal data.

- Job `#4` reached `ready_to_save`.
- `POST /rest/api/report-ai-job/4/save` -> `report_id=86`.
- `GET /rest/api/report-ai-job/4/data` -> columns `["ID Клиента", "Баланс"]`, `total=2`, `limited=false`.
- Rows:
  - `ID Клиента=424`, `Баланс="-452.0000000000"`
  - `ID Клиента=16`, `Баланс="-225.0000000000"`
- Control check via direct `/rest/api/client` filter `balance < 0` returned the same two IDs/balances.

## Important behavior

- `save` creates persistent reports visible in Vetmanager report constructor. This is a write side effect.
- `data` is available only for `saved` or `existing_report_matched`.
- `ready_to_save` exposes recognized structure and preview summary, but not preview rows.
- Queue latency is variable. Jobs can remain `queued` for several minutes before moving to `ready_to_save`.
- Job creation itself persists a `report_ai_jobs` row, even if no report is saved.
- Safe job view strips raw SQL from `recognized`.
- Saved reports must use meaningful titles so Vetmanager users can understand why the report appeared.
- `intent_text` is trimmed, must be non-empty, and is limited to 1000 characters.
- Create has 24-hour deduplication by normalized intent + clinic/user/API-key context; repeated creates may return `is_deduplicated=true` and an existing active job.
- `save` is valid from `ready_to_save`; if the job is already `saved`, it is idempotent and returns the existing `report_id`.
- `save` request body is strict and accepts only `title`.
- `getData` returns at most 1000 rows to the MCP/client side; `limited=true` means the rendered report has more rows than returned.
- `confirm` is valid only from `needs_confirmation`; `report_id` must be one of the job candidates.
- Safe job payload from `ReportAiJob::toSafeArray()` includes `candidates`; source-level candidate shape from `ExistingReportFinder` is `report_id`, `title`, and `match_score`. This branch was not observed at runtime on `devtr6` during research.
- `save` is not valid from in-progress states (`queued`, `recognizing`, `building_preview`) and should preserve `409 INVALID_TRANSITION`.
- MCP should enforce trimmed non-empty and <=1000-character `intent_text` client-side before calling upstream.

## Endpoint contract handoff

All endpoints are under the Vetmanager REST base path (`/rest/api/...` in MCP usage; extjs comments use `/api/...` internally).

| MCP action | Vetmanager endpoint | Body | Success data | Important errors |
| --- | --- | --- | --- | --- |
| Create job | `POST /rest/api/report-ai-job` | `{ "intent_text": "..." }` | `{ job, is_deduplicated }` | `400 VALIDATION_ERROR` for empty/long intent |
| View job | `GET /rest/api/report-ai-job/{id}` | none | `{ job }` | `404 NOT_FOUND`, `403 FORBIDDEN` |
| Confirm candidate | `POST /rest/api/report-ai-job/{id}/confirm` | `{ "report_id": 123 }` | `{ report_id }` | `409 INVALID_TRANSITION`, `400 VALIDATION_ERROR` |
| Save report | `POST /rest/api/report-ai-job/{id}/save` | `{ "title": "..." }` | `{ report_id, is_idempotent }` | `409 INVALID_TRANSITION`, `400 VALIDATION_ERROR`, `500 SAVE_FAILED` |
| Get data | `GET /rest/api/report-ai-job/{id}/data` | none | `{ columns, rows, total, limited }` | `409 INVALID_TRANSITION`, `500 PREVIEW_FAILED` |

Known statuses from source:

- In progress: `queued`, `recognizing`, `building_preview`.
- Usable without save: `existing_report_matched`.
- Usable after explicit save: `saved`.
- Needs user/agent choice: `needs_confirmation`.
- Failed terminal states: `failed`, `rejected`.
- Preview-only state: `ready_to_save`; this is not a data-readable state.

Known transitions from source:

- `queued -> recognizing | failed`
- `recognizing -> building_preview | failed | needs_confirmation | existing_report_matched`
- `building_preview -> ready_to_save | rejected | failed`
- `ready_to_save -> saved | failed`
- `needs_confirmation -> building_preview | existing_report_matched | rejected | failed`

## Proposed MCP surface

### Prompt/resource

`report_ai_prompt_helper`

- Returns the short prompt helper.
- MCP implementation should use `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md` as the adapted short helper text.
- Used by external agents before creating report jobs.
- Purpose: convert a user’s business question into a safe Russian `intent_text`.
- It must remind the agent to ask clarifying questions only when ambiguity materially changes the result, such as revenue basis, new-client definition, balance sign when not specified, repeat-visit window, clinic-specific directory values, and contact-list purpose.
- It must remind the agent that rows are unavailable until `saved` or `existing_report_matched`.

### Read/control tools

`create_report_ai_job(intent_text: str) -> dict`

- Calls `POST /rest/api/report-ai-job`.
- Returns `job`, `is_deduplicated`.
- Tool description must state that this persists a job row and starts async processing.
- Tool should surface `is_deduplicated`; if true, agent should continue polling/using the returned existing job instead of creating another.

`get_report_ai_job(job_id: int) -> dict`

- Calls `GET /rest/api/report-ai-job/{id}`.
- Returns safe job view.
- External agents poll this until one of:
  - `ready_to_save`
  - `existing_report_matched`
  - `needs_confirmation`
  - `saved`
  - `failed`
  - `rejected`
- Must support user-visible queued/processing status.
- Recommended agent policy: poll with a bounded timeout. If the job is still queued/processing, return the `job_id`, current status, and a resume instruction instead of blocking indefinitely.
- For `needs_confirmation`, the safe job payload must expose `job.candidates[]` with candidate `report_id`s. External agents cannot call confirm without these IDs.

`confirm_report_ai_job_candidate(job_id: int, report_id: int) -> dict`

- Calls `POST /rest/api/report-ai-job/{id}/confirm`.
- Only valid from `needs_confirmation`.
- Moves job to `existing_report_matched`.
- Tool must not accept arbitrary report IDs outside returned candidates.
- If MCP does not do client-side candidate membership validation, it must preserve the server `VALIDATION_ERROR` response when an arbitrary `report_id` is rejected.

`get_report_ai_job_data(job_id: int) -> dict`

- Calls `GET /rest/api/report-ai-job/{id}/data`.
- Valid only for `saved` or `existing_report_matched`.
- Returns `columns`, `rows`, `total`, `limited`.
- Tool description must mention the 1000-row MCP/client cap and `limited=true` behavior.

### Explicit write tool

`save_report_ai_job_as_report(job_id: int, title: str) -> dict`

- Calls `POST /rest/api/report-ai-job/{id}/save`.
- Must be marked write/sensitive because it creates a persistent report.
- Must require a meaningful report title, for example `MCP debtors by negative balance 2026-06-15`.
- Should not be hidden behind read-only tool names.
- If the server returns `is_idempotent=true`, the MCP tool should report that no new report was created and return the existing `report_id`.
- Valid source state is `ready_to_save`; already `saved` is idempotent. Calls from in-progress states should surface `INVALID_TRANSITION`.

### Optional orchestration prompt

`plan_report_ai_requests`

- Takes a natural-language analytical task.
- Uses `report_ai_prompt_helper` policy.
- Returns:
  - clarification questions, or
  - one or more `intent_text` requests,
  - merge instructions for the external agent.
- This should be a prompt, not a tool, because the agent performs the orchestration and may need multiple jobs.

## External agent flow

1. Read `report_ai_prompt_helper`.
2. Decide whether clarification is required.
3. Build one or more `intent_text` values.
4. Call `create_report_ai_job`.
5. Poll with `get_report_ai_job`.
6. If `existing_report_matched`, call `get_report_ai_job_data`.
7. If `needs_confirmation`, call `confirm_report_ai_job_candidate` only when a candidate is selected/approved.
8. If `ready_to_save`, present recognized structure and preview summary.
9. To get rows from `ready_to_save`, call `save_report_ai_job_as_report` with a meaningful title, then `get_report_ai_job_data`.
10. If polling times out before a usable state, return the `job_id` and current status so the agent/user can resume.

## Implementation notes for Stage 170

- Source-of-truth files to re-open during implementation:
  - `ReportAiJobsController.php` for strict request schemas and response wrapper.
  - `JobService.php` for validation, dedupe, save/data semantics, and row limit.
  - `JobStatus.php` for status names and transitions.
  - `ReportAiJob.php` for safe job payload fields.
  - `HttpErrorMapper.php` and `JobException.php` for error-code mapping.
- `docs/report-ai-api.md` is referenced by extjs comments but was not found in the checked repository path; do not rely on it unless it appears later.
- MCP tests should include strict-body behavior: create accepts only `intent_text`, save only `title`, confirm only `report_id`.
- MCP tests should preserve server error semantics rather than converting `INVALID_TRANSITION` into a generic failure.
- Real-smoke tests should avoid creating visible reports by default. Prefer existing saved/matched fixtures for data reads; same-run save should be opt-in via an explicit test env flag because create dedupe is only 24h and save idempotency is per job, not per report title.

## Open implementation questions

- Should MCP expose a combined convenience tool that performs create + polling only, without save?
- Persistent test reports created before Stage 170 implementation (`#84`, `#86`) are left as research evidence. Stage 170 real smoke should use them opportunistically for saved-data checks, but must skip gracefully if they are unavailable.
