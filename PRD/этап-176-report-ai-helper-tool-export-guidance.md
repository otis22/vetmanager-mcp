# Этап 176. Report AI helper tool and export fallback guidance

## Контекст

Пользователь уточнил два UX-риска в Report AI workflow:

- `start_report_export` / `get_report_export_file` выглядят для агента как обычный путь получения отчёта, хотя export должен быть fallback или явный путь по известному `report_id`.
- Подсказка для формулировки Report AI intent уже есть как MCP prompt `report_ai_prompt_helper`, но часть клиентов/агентов показывает только tools и не даёт агенту обнаружить prompts.

## Проверенные факты

- `prompts.py::report_ai_prompt_helper` уже читает `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md`.
- Artifact уже MCP-адаптирован: не содержит клиентский marker `МОЙ ВОПРОС`, copy-paste инструкцию для владельца клиники и не требует runtime credentials в prompt args.
- `tools/list` является source of truth для автоподбора tool клиентом/LLM; часть клиентов может не показывать MCP prompts.
- Tool wrapper fail-closed проверяет `tool_access_registry.py::TOOL_REQUIRED_SCOPES`; baseline tools должны быть явно разрешены в `tools/__init__.py::BASELINE_ALLOWED_TOOLS`.
- `report_problem` — существующий пример baseline tool: он имеет `TOOL_REQUIRED_SCOPES["report_problem"] = ()`, включён в `BASELINE_ALLOWED_TOOLS`, доступен без доменного scope, но всё равно требует authenticated bearer token с непустым scope manifest.
- Report export tools уже работают только по известным IDs на уровне реализации:
  - `start_report_export(report_id, filter_json=None)` вызывает `/rest/api/report/StartReport`;
  - `get_report_export_file(report_file_id)` вызывает `/rest/api/report/reportFile`;
  - `get_report_ai_job_export(job_id, filter_json=None)` стартует export только для `saved`/`existing_report_matched` jobs с `job.report_id`.
- Список отчётов по REST не подтверждён; `list_reports` tool не добавлять.

## Цель

Сделать для агентов очевидным default Report AI path:

1. Получить helper guidance.
2. Сформулировать русский `intent_text`.
3. Создать и poll-ить Report AI job.
4. Получать rows через `get_report_ai_job_data`.
5. Использовать CSV/XLSX export только как explicit/fallback path.

## Scope

### In scope

- Добавить tool `get_report_ai_prompt_helper`, возвращающий тот же rendered helper text, что prompt `report_ai_prompt_helper`: bearer runtime prefix + artifact body.
- Вынести чтение helper artifact в общий loader, чтобы prompt и tool не дублировали текст.
- Сделать helper tool baseline-allowed: `TOOL_REQUIRED_SCOPES["get_report_ai_prompt_helper"] = ()` и membership в `BASELINE_ALLOWED_TOOLS`; обычная bearer authentication и непустой scope manifest сохраняются.
- Обновить tool descriptions для Report AI/export guidance.
- Обновить runtime/KB hints, которые сейчас ссылаются только на prompt `report_ai_prompt_helper`, чтобы они также называли tool `get_report_ai_prompt_helper`.
- Обновить tests/docs/Roadmap/AssumptionLog.

### Out of scope

- Не менять upstream Vetmanager API.
- Не добавлять list reports tool.
- Не менять фактическую реализацию export endpoints.
- Не делать helper mandatory enforcement перед `create_report_ai_job`; это advisory guidance, не enforceable runtime rule. Валидный `create_report_ai_job(intent_text=...)` должен продолжать выполняться без предварительного helper call.
- Не заменять helper artifact текстом из `/home/otis/Downloads/ai-reports-client-prompt-short.md` без отдельного diff/review; текущий artifact используется как source of truth.

## Functional requirements

1. `get_report_ai_prompt_helper` должен быть MCP tool без аргументов.
2. Tool должен возвращать rendered helper text: тот же bearer runtime prefix, что prompt, плюс helper text из `artifacts/report-ai-prompt-helper-short-mcp-2026-06-15.md`.
3. Prompt `report_ai_prompt_helper` и tool `get_report_ai_prompt_helper` должны использовать общий loader и возвращать один и тот же rendered helper body. Tool может оборачивать body в structured response, но сравниваемое поле должно быть byte-for-byte equal raw rendered prompt text: `"\n".join(message.content.text for message in prompt.render(...).messages)` equals `tool_result.structured_content["helper_text"]`, без нормализации whitespace/line endings.
4. `get_report_ai_prompt_helper` должен быть разрешён authenticated bearer token с любым непустым scope manifest, включая tokens без `SCOPE_ANALYTICS_READ` и без `SCOPE_REPORT_AI_WRITE`. Empty/no-scope credentials остаются denied по существующему baseline pattern.
   `helper_text` key должен оставаться безопасным для depersonalization sanitizer; depersonalized tokens не должны менять helper text.
5. `create_report_ai_job` description должен говорить: сначала использовать `get_report_ai_prompt_helper` tool или `report_ai_prompt_helper` prompt, если пользователь не дал готовый русский `intent_text`.
6. `get_report_ai_job_data` description должен говорить: если response содержит `limited=true`, сначала сузить отчёт периодом/фильтрами/агрегацией; CSV/XLSX export — fallback only when the user still needs all rows and a `report_id` is available. Реализация tool output не меняется, меняется только guidance в description.
7. Export tool descriptions must be fallback-only / not default:
   - `start_report_export`: only when user gave known `report_id`, explicitly asks CSV/XLSX, or limited Report AI data needs full export and `report_id` exists.
   - `get_report_export_file`: only after `start_report_export`, not a discovery/list step.
   - `get_report_ai_job_export`: only for `saved`/`existing_report_matched` jobs with `job.report_id`; does not auto-save `ready_to_save`.
8. Descriptions must continue to include domain synonyms and no legacy credential hints.
9. Goods `good.id` workaround hints in `tools/report_ai.py` and seeded known issue content must mention `get_report_ai_prompt_helper` alongside `report_ai_prompt_helper`, so tool-only clients can discover the guidance.

## Acceptance criteria

- Test: `get_report_ai_prompt_helper` is registered in `tools/list`.
- Test: `get_report_ai_prompt_helper` output includes the same key boundaries as prompt helper (`ready_to_save`, `saved`, `existing_report_matched`, `Do not write SQL`, `good.id`, `код/артикул/наименование товара`).
- Test: `"\n".join(message.content.text for message in prompt.render(...).messages)` equals `tool_result.structured_content["helper_text"]` byte-for-byte, без whitespace normalization.
- Test: scope enforcement allows `get_report_ai_prompt_helper` with a bearer token that has any non-empty unrelated scope, for example `SCOPE_CLIENTS_READ`, and lacks `SCOPE_ANALYTICS_READ`/`SCOPE_REPORT_AI_WRITE`.
- Test: empty scope credentials still fail for helper tool, matching existing baseline tool behavior.
- Test: depersonalized bearer token receives identical `helper_text`; sanitizer must not redact or rewrite static helper guidance.
- Test: access registry has explicit mapping for the new tool and no stale mapping.
- Test: descriptions for `create_report_ai_job`, `get_report_ai_job_data`, `start_report_export`, `get_report_export_file`, `get_report_ai_job_export` contain the new guidance.
- Test: `create_report_ai_job` description explicitly contains `get_report_ai_prompt_helper` and `report_ai_prompt_helper`.
- Test: `get_report_ai_job_data` description explicitly names `limited=true`, narrow/refine first, and export fallback only when all rows are still needed and `report_id` is available.
- Test: Report AI goods `good.id` workaround output and seeded known issue playbook mention `get_report_ai_prompt_helper`.
- Test: existing `create_report_ai_job` success path with valid `intent_text` still works without any prior helper call; helper is advisory only.
- Existing Report AI, scope enforcement and tools/list schema tests remain green.

## Decomposition

1. Helper loader: add shared helper-path/text function in `prompts.py` or small module; wire `report_ai_prompt_helper` to it.
2. Tool: add `get_report_ai_prompt_helper` in `tools/report_ai.py`, returning the shared helper text.
3. Access: add explicit `TOOL_REQUIRED_SCOPES["get_report_ai_prompt_helper"] = ()` and include it in `BASELINE_ALLOWED_TOOLS`.
4. Descriptions: update `tool_descriptions.py` for helper and fallback export guidance.
5. Runtime/KB hints: update goods `good.id` workaround and seeded known issue text to reference both helper access paths.
6. Tests: add prompt/tool equality, helper scope behavior, description guidance, runtime hint and mapping coverage.

## Risks

- Duplicate prompt/tool surfaces can drift if they do not share a loader.
- Marking helper tool under report scopes would hide the guidance from tokens that need it most.
- Overstating "must call helper" as enforceable behavior would create false confidence; descriptions can guide but not guarantee agent behavior.
- Export locators remain sensitive bulk clinic data; descriptions must keep sensitive-locator warning.
