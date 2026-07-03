# Этап 183. Report AI upstream contract sync

## Контекст

Vetmanager обновил Report AI после предыдущих этапов 170/172/176. Текущий MCP контракт теперь устарел в нескольких местах: лимит `intent_text`, лимит строк `/data`, export guidance, `needs_confirmation` workflow и `good.id` known issue.

## Проверенные факты

- В `vetmanager-extjs` upstream `JobService::INTENT_MAX_LENGTH = 20000`.
- В `vetmanager-extjs` upstream `JobService::DATA_ROW_LIMIT = 10000`.
- `JobService::getData()` возвращает `csv_export_url = /rest/api/report/startReport?report_id=...`.
- `AiReportFacade::insertReport()` создаёт AI reports с `allow_rest_api=1`.
- Миграция `m260623_120000_RC_enable_rest_api_for_ai_reports` включает `allow_rest_api=1` для уже существующих AI reports.
- `ReportAiJob::toSafeArray()` whitelist отдаёт `preview_example_row`, но не отдаёт internal `analysis_type`/`period_range`.
- Upstream `PromptBuilder` требует `preview_example_row` как одну правдоподобную вымышленную строку примера, а `RecognizedReport` обнуляет поле, если оно не объект. Это поле остаётся LLM-generated preview metadata, не live rendered data, но его всё равно нельзя трактовать как факт из клиники.
- `needs_confirmation` достигается при похожих saved reports; `confirm(report_id)` переводит job в `existing_report_matched`.
- Real API `devtr6` принял `intent_text` длиной 1200 символов.
- Real API `devtr6`: `job_id=46` перешёл `needs_confirmation → existing_report_matched` через `report_id=84`; `/data` вернул rows и `csv_export_url`.
- Real API `devtr6`: `job_id=2/report_id=84` экспортируется через `StartReport → reportFile`.
- `StartReport` возвращает HTTP 403 не только для REST-deny, но и для busy/rate-limit states.
- Upstream `SubqueryExpander` содержит fix для view alias в CTE/повторных упоминаниях; real goods/ABC/XYZ e2e ещё не подтверждён.

## Цель

Синхронизировать MCP tools, prompts, descriptions, docs, tests и known issues с новым upstream contract без утечки raw SQL/PII и без скрытого write behavior.

## Scope

### In scope

- Поднять MCP client-side `intent_text` limit до 20000.
- Обновить `get_report_ai_job_data` contract до 10000 rows и штатного `csv_export_url`.
- Обновить Report AI tool docstrings и `tool_descriptions.py`.
- Обновить prompt helper artifact.
- Уточнить `needs_confirmation → confirm → existing_report_matched → data` flow.
- Признать `preview_example_row` safe field и описать его как пример, не реальные данные.
- Улучшить export error handling для разных 403 messages.
- Обновить `report-ai-goods-good-id-preview` seed known issue и runtime workaround как legacy/contour-specific.
- Обновить README Report AI section.
- Добавить/обновить unit/mock tests и opt-in real e2e branch.

### Out of scope

- Изменение `vetmanager-extjs`.
- Удаление `good.id` workaround до real goods/ABC/XYZ e2e.
- Добавление `list_reports` MCP tool.
- Автоматическое сохранение `ready_to_save` jobs из read-looking tools.
- Вывод raw SQL, hidden upstream fields или export file locators в logs.

## Архитектурное решение

### Проблема

MCP сейчас содержит локальную проекцию upstream Report AI контракта. Эта проекция дрейфует: часть ограничений стала мягче, часть workflow стала богаче, а часть fallback-подсказок теперь неверно описывает штатный upstream путь.

### Контекст и ограничения

- Existing pattern: Report AI tool surface lives in `tools/report_ai.py`; registry descriptions live in `tool_descriptions.py`; shared prompt text lives in `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md`.
- API contract: Report AI endpoints strict-schema validate request bodies; `confirm` принимает только `report_id` из `job.candidates`.
- Security/privacy: MCP must not expose raw SQL, API keys, domains, PII, or bulk export locators outside tool responses.
- Backward compatibility: existing clients may still see old `saved`/`ready_to_save` paths; descriptions must keep those flows.
- Performance/load: `/data` remains capped; full bulk reads go through export, not unbounded JSON.
- Performance/load: 10000 inline JSON rows can be too large for MCP clients/LLM context. MCP must preserve upstream rows but add safe guidance when totals approach the cap or `limited=true`.
- Production behavior: `StartReport` 403 must be interpreted by safe message, not collapsed into one permanent denial.
- Production behavior: 403 message parsing is free-text and therefore fragile; unknown 403 messages must get a conservative bounded-retry/error guidance instead of infinite retry or false permanent denial.

### Рассмотренные варианты

1. Minimal limits-only update.
   - Плюс: быстро.
   - Минус: leaves wrong guidance for confirm/export/known issues.
2. Full sync in one stage.
   - Плюс: one coherent contract update, tests catch cross-file drift.
   - Минус: touches several docs/tests.
3. Split into multiple stages.
   - Плюс: smaller diffs.
   - Минус: interim state still misleads agents and users.

### Выбранное решение

Сделать full sync in one stage, но держать изменения механическими и локальными: code constants/error handling, tool descriptions, helper/docs, seed known issue and tests. Это устраняет drift целиком без добавления новых MCP tools или новых storage/auth boundaries.

### Инварианты

- `create_report_ai_job` still sends strict body `{"intent_text": ...}` only.
- `confirm_report_ai_job_candidate` still sends strict body `{"report_id": ...}` only.
- Rows are still unavailable from `ready_to_save` without explicit save.
- `save_report_ai_job_as_report` remains the only save/write tool.
- Export locators may be returned by explicit export tools and by the upstream `/data` `csv_export_url` field, but must never be emitted to runtime logs/metrics.
- Raw SQL and hidden matching fields are not exposed.

### Rollback/fallback

If a contour still enforces old limits, upstream returns `VALIDATION_ERROR`; MCP preserves upstream errors. If goods/ABC/XYZ failures persist, the narrowed known issue remains available. If export is busy/rate-limited, MCP tells agents to retry later with bounded polling guidance. If export returns an unknown 403 message, MCP treats it as an ambiguous Vetmanager export denial/temporary limit and does not claim that REST access is permanently disabled.

Architecture Critique: required because this stage changes public MCP contract, production behavior, performance/load limits and known issue guidance.

## Functional requirements

1. `create_report_ai_job` accepts non-empty `intent_text` up to 20000 chars and rejects 20001 before upstream.
2. All Report AI descriptions mentioning intent length say 20000.
3. All data descriptions mentioning row cap say 10000.
4. `/data` test fixtures may include `csv_export_url`; descriptions treat it as supported export pointer.
4b. `csv_export_url` and export file locators must not be written to runtime logs or metrics when `/data` returns them.
4a. `get_report_ai_job_data` adds safe MCP guidance when `limited=true` or `total` is at/near the 10000 row cap: avoid pasting huge tables into chat, prefer narrowing or CSV/XLSX export for bulk review.
5. `needs_confirmation` descriptions must explain candidate selection and confirm result.
6. `confirm_report_ai_job_candidate` descriptions must say success enables `get_report_ai_job_data` without save.
6a. Backward compatibility boundaries must remain tested: `ready_to_save` still cannot return rows without explicit save, `existing_report_matched` can return rows without save, and read/data/export helper tools must not trigger `save`.
7. `preview_example_row` descriptions must say it is LLM-generated example preview metadata, not a verified live row from clinic data.
8. `_safe_export_error()` must distinguish REST-deny, busy/in-progress and 10-minute/rate-limit 403 messages.
8a. Unknown `StartReport` 403 messages must use conservative ambiguous export-denied/temporarily-limited wording with bounded retry guidance; tests must cover this default branch.
9. Seed known issue `report-ai-goods-good-id-preview` must match only explicit `good.id`-like failures, not generic товар/goods preview failures.
10. Runtime `mcp_workaround` text must align with seed playbook.
11. README and helper must describe the canonical flows:
    - `create → poll → ready_to_save → save → data`;
    - `create → poll → needs_confirmation → confirm → data`;
    - `saved/existing_report_matched → data/export`.

## Decomposition

1. PRD/review gates: create PRD, run Architecture Critique/PRD review gates, record findings.
2. Limits/data code/tests: update constants, docstrings, mock tests.
3. Data payload guidance/tests: add safe large-result guidance for `limited=true`/near-cap totals without dropping upstream rows.
4. Export error handling/tests: update `_safe_export_error()` and export tests including unknown 403.
5. Prompts/descriptions/docs: update helper artifact, `tool_descriptions.py`, README and description tests.
6. Known issue/workaround/tests: update seed, runtime workaround and feedback tests.
7. Real e2e: add/adjust opt-in real test branch for long intent and confirm flow where fixture candidates exist.
8. Checks/reviews: targeted tests, full suite, opt-in real checks, audit, Spark/Claude diff reviews, AssumptionLog/Roadmap finalization.

## Acceptance criteria

- Unit/mock tests cover new 20000/20001 boundary.
- Unit/mock tests cover 10000 row cap wording and `csv_export_url`.
- Unit/mock tests cover that `csv_export_url` from `/data` is preserved in tool response but absent from runtime logs/metrics.
- Unit/mock tests cover `mcp_large_result_guidance` or equivalent safe guidance for `limited=true`/near-cap totals.
- Unit/mock tests cover `needs_confirmation → confirm → data` behavior.
- Unit/mock tests cover no-hidden-write compatibility: `ready_to_save` data remains `INVALID_TRANSITION`, confirmed/existing matched data works without save, and data/export helper flows do not call `/save`.
- Unit/mock tests cover `preview_example_row`.
- Unit/mock tests cover export 403 split.
- Unit/mock tests cover unknown export 403 default wording.
- Feedback seed tests confirm narrower `good.id` matching and no generic goods false positive.
- README/helper/descriptions no longer claim 1000 intent/data row limits or unsupported AI export.
- Full Docker test suite passes.
- Opt-in real Report AI checks are run or documented as skipped with reason.
- `AssumptionLog.md` records accepted/rejected review findings and real-check status.
