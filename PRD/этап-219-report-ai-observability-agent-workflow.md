# Этап 219. Наблюдаемость Report AI и агентский workflow

## Цель

Сделать MCP-наблюдаемым фактический путь Report AI: создание job, наблюдаемые
переходы, исход и длительность стадий, а также отдельный export flow. Это
должно отделять длительную очередь от API-ошибки и от прекращения polling
агентом. Одновременно зафиксировать конкретные, но пока не реализуемые,
MCP-only улучшения поверхности для надёжной работы агентов.

## Проверенные факты и границы

- `tools/report_ai.py` обращается к `VetmanagerClient` напрямую, поэтому не
  проходит через common `crud_helpers` instrumentation. В результате
  `vetmanager_tool_calls_total` и latency metric не содержат вызовы Report AI.
- Публичный API contract использует async job create, чтение job/status,
  explicit candidate confirm/save, чтение data и отдельный two-step export.
  Rows доступны только для `saved` и `existing_report_matched`; save является
  явным write action.
- Подтверждённые status strings, наблюдаемые MCP: `queued`, `recognizing`,
  `building_preview`, `ready_to_save`, `needs_confirmation`, `saved`,
  `existing_report_matched`, `failed`, `rejected`.
- Существующий `vetmanager_report_ai_long_queued_polls_total` уже считает
  каждый observed poll старше локального 30-second threshold. Его semantics,
  name и increment не изменяются и не дублируются.
- MCP не получает public upstream TTL, `retry_after`, server-side queue reason
  или id export file в job status. Все новые duration значения — только
  process-local monotonic observations, не upstream SLA и не diagnosis
  внутренней очереди.
- Не записывать в repository сведения о внутренней реализации Vetmanager;
  использовать только API contract и поведение текущей MCP surface.

## Scope

1. Подключить существующую `instrument_call` к каждому фактическому Report AI
   API request, с постоянным `tool_name`; этим восстановить normal
   `vetmanager_tool_calls_total` / latency series без смены существующих
   label semantics.
2. Добавить bounded process-local lifecycle observer, tenant-scoped по runtime
   account/connection и job ID. Он сохраняет первый observed момент и текущую
   canonical stage, а не intent, rows, title, report ID, URLs или API payload.
3. Экспортировать bounded metrics:
   - создание job (`vetmanager_report_ai_jobs_total{outcome}`);
   - переходы (`vetmanager_report_ai_job_transitions_total{from_stage,to_stage}`);
   - terminal outcome (`vetmanager_report_ai_job_terminal_outcomes_total{outcome}`);
   - observed duration каждой stage и end-to-end job
     (`vetmanager_report_ai_job_stage_duration_seconds`,
     `vetmanager_report_ai_job_duration_seconds`);
   - отдельные export attempts/outcomes/duration
     (`vetmanager_report_ai_exports_total`,
     `vetmanager_report_ai_export_duration_seconds`).
4. Стадии нормализовать в малый fixed set: `queued`, `recognized`, `preview`,
   `ready_to_save`, `needs_confirmation`, `saved`, `existing_report_matched`,
   `failed`, `rejected`, `unknown`. Нормализация — MCP vocabulary: raw
   `recognizing` maps to `recognized`, raw `building_preview` maps to
   `preview`; незнакомый raw status maps to `unknown`.
5. Считать usable completion при `saved` или `existing_report_matched`; API
   terminal failure — `failed`/`rejected`. Если observer state истёк после
   отсутствия следующего job poll, записать `abandoned_wait`: это означает
   только «MCP более не наблюдал polling до local TTL», а не утверждение о
   состоянии job или намерениях агента. Метрики lifecycle считают local
   observations, не уникальные jobs: каждый observation finalizes exactly
   once, но `abandoned_wait` удаляет local observation и следующий poll после
   TTL начинает новый observation. Поэтому одно job может дать отдельные
   `abandoned_wait` и later terminal samples; это не exactly-once job metric.
6. Export измерять отдельно: старт export и polling export file; successful
   file response завершает observed export. Для convenience path связывать
   report-AI job с export attempt только в памяти; direct known-`report_id`
   export остаётся export-only и не выдумывает job transition. Наблюдаемый
   API-контракт `reportFile`: «export ещё не готов» приходит как HTTP 409 или
   как HTTP 401 с фиксированным сообщением `build in progress`; MCP использует
   единый classifier для guidance и метрик. Маркеры `build in progress` и
   `not started` действуют только внутри наблюдённых статусов 401/409; за их
   пределами текст не означает готовность. При local TTL/LRU abandonment
   export без file poll учитывается как `start|abandoned_wait`, после хотя бы
   одного file poll — как `poll|abandoned_wait`.
7. Добавить targeted tests и README contract, включая отсутствие sensitive
   labels/payload data и сохранение legacy long-queued metric.
8. В PRD описать фактический agent journey и MCP-only предложения. Не менять
   tool surface, descriptions или workflow из этих предложений в этом этапе.

## Вне scope

- Изменения Vetmanager API, worker/queue, SQL generation или их контрактов.
- Изменение лимитов intent/rows.
- Автоматический retry, save, confirmation или export.
- Добавление upstream TTL/SLA/reason в MCP result.
- Production/SSH checks, push, и реализация предложений из раздела ниже.

## Архитектурное решение

### Проблема

Общий tool instrumentation отсутствует у ручного Report AI client path.
Существующий long-queue counter показывает симптом poll, но не создание,
переход, исход или время пути. Нельзя отличить observed failure от того, что
agent просто перестал опрашивать job.

### Варианты

1. Встроить всё в `crud_helpers`.
   - Не покрывает прямой Report AI path без широкого рефакторинга.
2. Добавить самостоятельные ad-hoc counters прямо в tools module.
   - Дублирует registry/rendering и повышает риск несовместимых metrics.
3. Использовать common `instrument_call` для API requests, а lifecycle state и
   fixed-cardinality domain metrics разместить в `service_metrics`.
   - Покрывает пробел, сохраняет established exporter и ограничивает state.

### Выбранное решение

Вариант 3. `tools/report_ai.py` владеет interpretation ответов и bounded
per-job observation, `service_metrics.py` — thread-safe registry, snapshot и
Prometheus exposition. Observations привязаны к tenant context и не сохраняют
клинические данные. До первого status poll нельзя честно назвать stage, поэтому
creation и lifecycle duration являются разными metric families.

### Инварианты

- Existing general metrics и long-queued counter не меняют semantics.
- Labels имеют fixed allowlisted values; ID, domain, intent, report title, rows,
  URLs, raw error text и SQL в labels/metrics не попадают.
- API response и MCP public behavior не меняются ради измерения.
- `abandoned_wait` остаётся observed-local classification, не upstream failure.
- Исключения сохраняют current ToolError behavior; instrumentation не маскирует
  error и не создаёт повторный request.

### Rollback / fallback

Если observer даёт ненадёжный сигнал или создаёт overhead, отключить только
lifecycle calls/metric exposition, сохранив normal request instrumentation и
existing long-queued counter. При новом public status добавить его только в
fixed normalizer после API-contract evidence; до этого использовать `unknown`.

Architecture Critique: required, because the task adds public Prometheus
contract and a cross-module ownership boundary.

## Декомпозиция

1. 219.1: PRD, current-surface investigation, Architecture Critique and PRD
   review. ≤2h.
2. 219.2: common request instrumentation and bounded lifecycle metrics. ≤150
   LOC per focused change.
3. 219.3: mock tests, README metric contract, checks/audit/code review. ≤2h.
4. 219.4: document MCP-only proposals; no implementation. ≤2h.

## Agent journey as implemented now

1. Usually one helper call (unless the agent already has a ready Russian
   `intent_text`), then `create_report_ai_job`: 1–2 calls before a job ID.
2. `get_report_ai_job` is called repeatedly. In `queued`, `recognizing` and
   `building_preview` the agent has no action except bounded waiting. This is
   an unbounded number of calls and it is where the observed queue problem
   occurs.
3. `needs_confirmation` requires a decision: choose only a returned candidate
   and call confirm (one extra call), then data (one more). `ready_to_save`
   requires a different decision: user-authorized explicit save with a title
   (one call), then data (one). A read-only token cannot take this branch to
   rows, but it can see the state.
4. `saved`/`existing_report_matched` leads to one data call. Thus a simple
   ready-to-save-to-rows path is at least create + one or more polls + save +
   data; the candidate path is create + polls + confirm + data.
5. For bulk output, agent first needs a known `report_id`, starts export and
   repeatedly polls file status. This is again an unbounded wait; direct export
   requires a user-supplied known report ID. API errors are surfaced as
   ToolError; current tools do not expose a single atomic wait/result call.

## MCP-only proposals — not implemented in this stage

| Proposal | Feedback addressed | Cost / trade-off |
| --- | --- | --- |
| Add a single read-only `wait_for_report_ai_job` tool with explicit `max_polls` and `max_wait_seconds`, returning last safe job plus `wait_outcome=ready|terminal_failure|deadline_exceeded`. It performs bounded polls server-side and never retries/create/save. | Long `queued` reports; agents repeatedly polling without knowing when to stop. | New public MCP contract and server-held wait; needs timeout/cancellation/load limits and tests. Does not diagnose upstream queue. |
| Add a read-only `get_report_ai_job_progress` result that combines current safe job, canonical stage, observed elapsed time and next permitted action (`wait`, `choose_candidate`, `authorize_save`, `read_data`, `stop`). | Agents lack decision information at `needs_confirmation`/`ready_to_save`; read-only preset stalls at save. | New response contract; must be explicitly local observation and avoid promise of completion time. |
| Add a read-only `get_report_ai_job_rows_or_reason` convenience tool: for readable states fetch data; for `ready_to_save` return structured `write_required` rather than opaque upstream transition error; for terminal/in-progress return safe typed reason and next action. | Read-only job reaches `ready_to_save` but cannot obtain rows; agent wastes calls guessing `/data`. | A new wrapper must preserve no-hidden-write invariant and avoid duplicating large rows/errors. |
| Add one `create_or_reuse_report_ai_job` wrapper that always returns a normalized first action and deduplication context, without automatic retry or polling. | Duplicate recreation after queue delay; agents need to decide whether a returned job is reusable. | Small surface improvement but must not hide create semantics; does not solve stuck queue. |
| Add an export wait wrapper with bounded poll budget and typed `not_ready`, `temporary_guard`, `not_exportable`, `deadline_exceeded`, `ready` outcomes. | Large export waits for hours and 403 ambiguity. | New public contract and bounded server work; no automatic 30-minute retry and no invented upstream reason. |
| Add MCP-side fallback planner in helper/progress response: when a report is stalled or too large, state whether a narrow re-request, data read, or export is currently possible; do not execute it. | Manual split-period/recreate and per-invoice fallback work. | Policy needs careful, testable rules; cannot guarantee semantic equivalence of a split report. |
| Add a safe SQL-failure classifier for explicit API-safe unknown-column errors, returning `generation_failed` plus “do not retry unchanged intent; rephrase without the rejected field”. | Generated SQL referring to non-existent columns. | Must use only safe returned error text and fixed markers; cannot expose SQL or promise the next intent succeeds. |

The feedback report identifiers/counts are operational evidence supplied by the
user; this repository records only the affected API/MCP behavior, not clinic
content or backend implementation details.

## Acceptance criteria

1. Report AI API calls appear in existing `vetmanager_tool_calls_total` and
   latency metrics with stable tool labels and success/error outcome.
2. New metrics answer creation volume, stage transitions, terminal outcomes,
   per-stage/total duration and export outcome/duration without high-cardinality
   or sensitive labels.
3. `failed`/`rejected`, observed `abandoned_wait`, and long queued are separate
   queryable classifications; legacy long-queued metric remains exactly once.
4. Tests cover success, error, known transitions, unknown status, failure,
   local abandonment, export success/error, tenant isolation and Prometheus
   exposition.
5. README documents exact metric names and the local-observation limitation.
6. All proposals above remain documentation only.
