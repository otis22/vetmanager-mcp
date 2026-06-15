# Этап 170. Report AI MCP tools and prompt helper

## Цель

Добавить MCP surface для Vetmanager Report AI так, чтобы сторонний агент мог безопасно сформулировать запрос, создать AI-report job, отслеживать её статус, подтверждать найденный существующий отчёт, явно сохранять отчёт при необходимости и получать табличные данные.

## Контекст

Пользователь предоставил prompt helpers:

- `ai-reports-client-prompt-short.md`
- `ai-reports-client-prompt-full.md`

Ожидаемый пользовательский сценарий: агент берёт short helper, формирует один или несколько запросов в AI reports и последовательно собирает данные. Исследование зафиксировано в `artifacts/report-ai-mcp-research-2026-06-15.md`.

Real API facts on `devtr6`:

- `POST /rest/api/report-ai-job` создаёт async job.
- `GET /rest/api/report-ai-job/{id}` возвращает safe view без raw SQL.
- `GET /rest/api/report-ai-job/{id}/data` работает только для `saved` или `existing_report_matched`.
- `POST /rest/api/report-ai-job/{id}/save` создаёт persistent report in Vetmanager.
- Job queue latency can be several minutes.
- Persistent reports must have meaningful titles; no additional approval workflow is required beyond the explicit write tool call.

Source-level facts from `vetmanager-extjs`:

- `intent_text` is required, trimmed, and limited to 1000 characters.
- Create deduplicates active jobs for 24 hours and can return `is_deduplicated=true`.
- REST bodies are strict: create only `intent_text`, confirm only `report_id`, save only `title`.
- Known statuses: `queued`, `recognizing`, `building_preview`, `ready_to_save`, `saved`, `failed`, `rejected`, `needs_confirmation`, `existing_report_matched`.
- `ready_to_save` is preview-only for MCP purposes; `/data` returns rows only for `saved` or `existing_report_matched`.
- `/data` caps returned rows at 1000 and returns `limited=true` when total exceeds that cap.
- `save` is idempotent for already saved jobs and returns `is_idempotent=true`.
- Safe job payload includes `candidates` for `needs_confirmation`; source-level candidate shape is `report_id`, `title`, and `match_score`. This branch was source-confirmed but not runtime-observed on `devtr6` during research.
- `save` is valid only from `ready_to_save`; already `saved` is idempotent; in-progress states must preserve upstream `INVALID_TRANSITION`.

## Scope

1. Add MCP prompt/resource `report_ai_prompt_helper`.
   - Always expose the short helper.
   - Do not expose the full helper by default.
   - Use the MCP-adapted short helper from `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md`.
   - Include calm clarification guidance: ask only when ambiguity materially changes the report; do not over-warn the user.
   - Include data-flow guidance: rows are unavailable before `saved`/`existing_report_matched`.
2. Add tool `create_report_ai_job`.
   - Input: `intent_text`.
   - Output: safe job payload and `is_deduplicated`.
   - Enforce client-side validation: trimmed `intent_text` must be non-empty and no longer than 1000 characters.
   - Preserve `is_deduplicated` so the agent can reuse the returned job.
3. Add tool `get_report_ai_job`.
   - Input: `job_id`.
   - Output: safe job payload.
   - For `needs_confirmation`, output must expose `job.candidates[]` with candidate `report_id`s so external agents can choose a valid candidate.
   - Tool description must explain polling, statuses, and queue latency.
   - Recommended agent policy: poll for a bounded period, then return `job_id` and current status so the caller can resume later.
4. Add tool `confirm_report_ai_job_candidate`.
   - Input: `job_id`, `report_id`.
   - Valid only for `needs_confirmation`.
   - Must document that `report_id` must come from the job candidates.
   - MCP may rely on server-side validation for candidate membership, but tests must preserve the server `VALIDATION_ERROR` shape when an arbitrary `report_id` is rejected.
5. Add tool `get_report_ai_job_data`.
   - Input: `job_id`.
   - Valid only for `saved` or `existing_report_matched`.
   - Must surface `columns`, `rows`, `total`, `limited`, including the 1000-row returned-row cap.
6. Add explicit write tool `save_report_ai_job_as_report`.
   - Input: `job_id`, `title`.
   - Valid only for `ready_to_save`; already `saved` is idempotent.
   - Must be classified/mapped as write-sensitive because it creates a persistent report visible in Vetmanager.
   - Must require a meaningful `title` that explains the requested report and period when applicable; empty/generic titles are rejected client-side.
   - Must surface `is_idempotent` and explain when an existing `report_id` was returned.
7. Add tests and docs that external agents can follow:
   - create/poll flow;
   - ready-to-save without data;
   - save then data;
   - existing-report matched path;
   - needs-confirmation path;
   - queue latency/poll timeout behavior.

## Out of Scope

- Writing SQL in MCP.
- Returning raw SQL from `recognized`.
- Automatically saving reports behind a read-only-looking tool.
- Exposing full prompt helper by default.
- Building a transient preview-data endpoint in Vetmanager.
- Deleting saved reports from Vetmanager.

## Acceptance Criteria

1. `mcp.get_prompt("report_ai_prompt_helper")` or equivalent resource returns the short helper.
2. `create_report_ai_job` starts a job and returns `queued`/deduplicated safe payload.
3. `get_report_ai_job` supports polling until terminal/usable states.
4. `get_report_ai_job_data` returns a clear `INVALID_TRANSITION` style error when called before `saved`/`existing_report_matched`.
5. `get_report_ai_job` exposes `candidates[]` with candidate `report_id`s for `needs_confirmation` jobs.
6. `save_report_ai_job_as_report` is explicit, write-classified, validates meaningful report titles, is valid only from `ready_to_save`, and surfaces idempotent already-saved results.
7. `create_report_ai_job` rejects empty and over-1000-character `intent_text` before calling upstream.
8. `save_report_ai_job_as_report` preserves `INVALID_TRANSITION` for in-progress states.
9. Tool docs tell external agents: to get rows from `ready_to_save`, call the explicit save tool with a meaningful title, then call data.
10. Mock tests cover all status branches.
11. Mock tests cover strict body validation, dedupe reuse, idempotent save, invalid transitions, confirm candidate exposure/validation, empty/long intent rejection, and `limited=true`.
12. Real `devtr6` smoke covers a simple non-PII report status/read path and a data read from an existing saved/matched job when available; it must not create unbounded visible reports on repeated runs.

## Real Smoke Policy

Real `devtr6` smoke must be bounded and non-polluting by default:

- Default real smoke may create/poll a job and read an already `saved` or `existing_report_matched` job when such a fixture is available.
- The known research fixtures are job `#2` / report `#84` and job `#4` / report `#86`, but tests must tolerate their absence or changed accessibility by skipping the saved-data assertion with a clear reason.
- Same-run real save is opt-in only and must require an explicit environment flag such as `TEST_REPORT_AI_ALLOW_SAVE=1`; without that flag, the real test must not call `/save`.
- If a fresh job does not reach `ready_to_save` within the bounded poll timeout, real smoke records/prints the job id in test output and skips same-run save/data assertions instead of failing on queue latency.
- Mock tests remain the authoritative coverage for save/data transitions, idempotent save, and invalid transitions.

## Проверки

During implementation:

```bash
docker compose --profile test run --rm test pytest tests/test_stage170_report_ai_tools.py -q
docker compose --profile test run --rm test pytest tests/test_tools_list_schema.py tests/test_stage130_access_registry.py -q
docker compose --env-file .env --profile test run --rm test python -m pytest tests/test_e2e_real.py -k 'report_ai' -q
docker compose --profile test run --rm test
git diff --check
python3 scripts/check_no_historical_api_key_literal.py
```
