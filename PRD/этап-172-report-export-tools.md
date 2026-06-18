# Этап 172.1. Report export tools

## Цель

Добавить MCP tools для существующего Vetmanager Report Constructor export flow, чтобы агент мог запускать CSV/XLSX выгрузку по известному `report_id` и получать ссылки/пути файлов по `report_file_id`, не меняя Vetmanager API.

## Контекст

Production feedback `#11` показал, что `get_report_ai_job_data` ограничен 1000 строками (`limited=true` при `total > 1000`). MCP-only получение строк за пределами 1000 невозможно через `/rest/api/report-ai-job/{id}/data`, потому что upstream режет rows в `JobService::DATA_ROW_LIMIT`.

Найден готовый REST flow:

- `GET /rest/api/report/StartReport?report_id=<id>&filter=<json>` -> `data.report.report_file_id`;
- `GET /rest/api/report/reportFile?file_id=<report_file_id>` -> `html_file`, `csv_file`, `csv_semicolon_file`, `xlsx_file`.

OpenAPI содержит только эти два report endpoints. REST endpoint списка отчётов не найден.

Important limitation: this does not remove upstream `get_report_ai_job_data` row cap for AI jobs whose saved report is not REST-exportable. The new export tools solve full CSV/XLSX output only for Report Constructor reports that already have `allow_rest_api=1`. For saved AI reports created by the current upstream save path, `get_report_ai_job_export` is expected to degrade gracefully with a clear unsupported error unless upstream/report settings make that report REST-accessible.

## Source facts

- `artifacts/vetmanager_openapi_v6.json` публикует `/rest/api/report/StartReport` и `/rest/api/report/reportFile`, but only with generic query params and untyped `data: object`; concrete `report_id`/`file_id` params and response fields come from upstream PHP source and must be verified by a real API probe before implementation.
- `ReportController::doCustomRestGetStartReport()` requires `report_id`, checks `allow_rest_api`, rate-limits REST report generation and returns `data.report.report_file_id`. Because this endpoint starts generation as a side effect, MCP must call it as a one-shot request without the generic GET retry loop.
- `ReportController::doCustomRestGetReportFile()` requires `file_id`; while status is not `done`, upstream returns HTTP 401 with status-specific messages (`build in progress`, `build is not started yet`, etc.); when done returns file names/paths.
- `Report::getReportFileById()` возвращает `html_file`, `csv_file`, `csv_semicolon_file`, `xlsx_file`.
- `AiReportFacade::insertReport()` currently saves AI reports with `allow_rest_api=0`; `get_report_ai_job_export` may therefore receive 403 for current saved AI reports.
- `VetmanagerError` carries `status_code`; 403-specific guidance is implementable by checking `exc.status_code == 403`.
- Real API probe on `devtr6`, report `74`, confirmed `StartReport` returns `data.report.report_file_id`; `reportFile` first returns transient not-ready and then returns `html_file`, `csv_file`, `csv_semicolon_file`, `xlsx_file`. File locator values were not printed and are treated as sensitive.

## Privacy and Security

- Returned `html_file`, `csv_file`, `csv_semicolon_file`, `xlsx_file` values are treated as sensitive report-export locators because exports can contain bulk clinic data and PII.
- Tool success payload may return these fields to the caller, but MCP logs and ToolError messages must not echo export locators, `filter_json`, `report_file_id`-derived URLs, or raw upstream bodies containing file paths.
- Error messages may include high-level status (`not ready`, `not REST-exportable`, upstream HTTP status/code) without copying sensitive URLs or filter contents.
- Real API probe must record whether returned file locators require Vetmanager authentication and whether they appear persistent or temporary. If this cannot be established safely, document them as sensitive persistent locators.

## Scope

1. Add read-only MCP tool `start_report_export(report_id: int, filter_json: str | None = None)`.
   - Calls `GET /rest/api/report/StartReport`.
   - Uses no automatic transport retry because repeated calls can start duplicate generation or hit upstream REST report rate limits.
   - Passes `report_id`; passes `filter` only when `filter_json` is non-empty.
   - Validates non-empty `filter_json` as parseable JSON before calling upstream.
   - Treats filter structure as report-specific/opaque unless the real probe confirms a canonical shape; document the silent full-export risk if upstream ignores malformed report-specific filters.
   - Returns `report_file_id` and raw safe upstream envelope metadata needed for follow-up.
   - Requires `analytics.read`.
2. Add read-only MCP tool `get_report_export_file(report_file_id: int)`.
   - Calls `GET /rest/api/report/reportFile`.
   - Returns `html_file`, `csv_file`, `csv_semicolon_file`, `xlsx_file`.
   - Validates that at least one expected export file field is present before returning success.
   - Preserves upstream not-ready errors as retryable tool guidance: report generation is still in progress, call `get_report_export_file` again after a delay.
   - Preserves original upstream code/status where available without echoing sensitive file locators.
   - Requires `analytics.read`.
3. Add convenience MCP tool `get_report_ai_job_export(job_id: int, filter_json: str | None = None)`.
   - Reads `GET /rest/api/report-ai-job/{job_id}`.
   - Uses explicit status allowlist: only `saved` or `existing_report_matched`.
   - Requires non-empty `job.report_id`.
   - Calls `StartReport` for that `report_id`.
   - If upstream returns 403 (`allow_rest_api=0`), surface a clear unsupported message.
   - Does not auto-save `ready_to_save` jobs.
4. Exclude `/rest/api/report/StartReport` and `/rest/api/report/reportFile` from GET response caching because they are generation/polling endpoints.
5. Update tool descriptions, access registry, token scope request mapping, README tool table/flow.
6. Tests cover tool registration, request params, access scopes, no-cache behavior, not-ready/403 handling, no list-reports tool.

## Out of Scope

- Changing Vetmanager API or upstream `allow_rest_api` behavior.
- Removing `DATA_ROW_LIMIT`.
- Returning all report rows as JSON.
- Adding a list reports tool.
- Auto-saving Report AI jobs.
- Downloading file bytes through MCP; tools return upstream file paths/URLs only.

## Acceptance Criteria

1. `start_report_export(report_id=88)` calls `/rest/api/report/StartReport` with `report_id=88` and omits `filter` when no filter is supplied.
2. `get_report_export_file(report_file_id=123)` calls `/rest/api/report/reportFile` with `file_id=123`.
3. `get_report_ai_job_export(job_id=22)` first reads the job, extracts `job.report_id`, then starts export.
4. `get_report_ai_job_export` rejects every status except `saved` and `existing_report_matched`, and rejects jobs without `report_id`, before `StartReport`.
5. 403 from `StartReport` is surfaced as "report is not REST-exportable" guidance, not hidden as a generic failure.
6. No `list_reports` / `get_reports` MCP tool is registered.
7. New tools require only `analytics.read`, not write scopes.
8. README documents the two-step flow and the lack of list endpoint.
9. Report export GET calls are not served from MCP request cache.
10. `required_scope_for_request("GET", "/rest/api/report/StartReport")` and `required_scope_for_request("GET", "/rest/api/report/reportFile")` return `analytics.read`.
11. A real API probe confirms param names, response paths, file field names, not-ready behavior, and privacy characteristics before implementation proceeds.
12. `StartReport` is invoked without automatic GET retry.
13. `reportFile` not-ready HTTP 401 is surfaced as retry guidance, while successful payloads without expected export fields are rejected as malformed.

## Decomposition

- 172.1a PRD/research/review gates. <= 2h, docs only.
- 172.1a-real Real API probe for `StartReport`/`reportFile` contract and privacy characteristics, skipped only if credentials are unavailable and recorded as blocker before implementation. <= 2h.
- 172.1b Tests: Report export MCP tools + access registry + no list tool. <= 2h, test-only.
- 172.1c Implementation in `tools/report_ai.py`, `tool_access_registry.py`, `tool_descriptions.py`, `token_scopes.py`, README. <= 2h, <=150 LOC.
- 172.1d Checks, audit, review gates, commit/push/deploy/smoke. <= 2h.

## Проверки

```bash
docker compose --profile test run --rm -e TEST_DOMAIN=<domain> -e TEST_API_KEY=<key> test python scripts/probe_report_export_contract.py
docker compose --profile test run --rm test pytest tests/test_stage172_report_export_tools.py tests/test_stage130_access_registry.py tests/test_tools_list_schema.py -q
docker compose --profile test run --rm test
git diff --check
```
