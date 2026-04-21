# Этап 122. VM API payload contract hotfix (camelCase → snake_case)

## Контекст

Super-review 2026-04-20 (`artifacts/review/2026-04-20-full-stage-121.md`) подтвердил production-blocker: несколько MCP tools продолжают отправлять в Vetmanager API camelCase payload/query-поля или legacy `extra`-параметры там, где реальный backend ждёт snake_case filter/payload. Vetmanager в этих случаях часто **молча игнорирует** неизвестные поля, что приводит к записям с пустыми core-полями и ложному ощущению успешной операции.

Затронутые точки:
- `tools/clinical.py::create_hospitalization` / `update_hospitalization`
- `tools/finance.py::create_payment`, `get_payments`, `add_invoice_document`, `get_invoice_documents`
- `tools/client.py::create_client`
- `tools/reference.py::get_breeds`
- `tools/operations.py::get_timesheets`

Основания для фикса:
- `artifacts/api-research-notes-ru.md`
- `artifacts/api_entity_reference-ru.md`
- выводы super-review stage 121

## Цель

Привести outbound contract этих tool'ов к реальным именам полей Vetmanager API, не меняя внешние MCP-сигнатуры без необходимости.

## Scope

**В scope:**
- payload/query field mapping только для перечисленных tool'ов;
- contract tests, которые проверяют фактический HTTP body/query;
- пополнение `artifacts/api-research-notes-ru.md` секцией по real field names.

**Вне scope:**
- массовый rewrite всех mutation contract tests по codebase;
- unhappy-path coverage для всех CRUD-инструментов;
- performance/reliability/docs cleanups из этапов 123-127.

## Подзадачи

### 122.1 PRD + test-first contract coverage (≤2 ч, ≤150 LOC на подзадачу)

- Создать/обновить целевые contract tests через `mcp.call_tool(...)`
- Зафиксировать expected body/query для:
  - hospitalization create/update
  - payment create/list
  - invoiceDocument create/list
  - client create
  - breed list with `pet_type_id`
  - timesheet list with `date`

### 122.2 clinical.py / finance.py mapping fix (≤2 ч, ≤150 LOC)

- `create_hospitalization`: `patient_id`, `doctor_id`, `date_in`, `hospital_block_id`
- `update_hospitalization`: `date_out`, `hospital_block_id`
- `create_payment`: `client_id`, `cassa_id`
- `get_payments`: filter on `client_id`, не `extra={"clientId": ...}`
- `add_invoice_document`: `invoice_id`, `good_id`
- `get_invoice_documents`: filter on `invoice_id`, не `extra={"invoiceId": ...}`

### 122.3 client.py / reference.py / operations.py mapping fix (≤2 ч, ≤150 LOC)

- `create_client`: `first_name`, `last_name`, `cell_phone`
- `get_breeds`: filter on `pet_type_id`
- `get_timesheets`: date-range filter по `begin_datetime`/`end_datetime` вместо `extra={"date": ...}`

### 122.4 API notes backfill (≤30 мин, ≤80 LOC)

- Добавить в `artifacts/api-research-notes-ru.md` расширение секции `## Поля и их реальные имена`
- Зафиксировать canonical names для Hospital / Payment / InvoiceDocument / Client create

### 122.5 Полный прогон + аудит (≤2 ч)

- `docker compose --profile test run --rm test`
- после правок отдельно проверить, что не осталось camelCase/legacy query contract в целевых tool'ах
- при необходимости небольшой refactor без изменения scope

## Верификация

- contract tests падают на старом контракте и проходят после фикса
- полный test suite зелёный
- `artifacts/api-research-notes-ru.md` содержит backfill по новым полям

## Риски

- Для `create_client.phone` есть ambiguity между `cell_phone` и `home_phone`; stage 122 фиксирует выбранное направление `cell_phone`, согласованное с roadmap и review. Если real API probe позже опровергнет, потребуется follow-up stage.
- `get_timesheets(date=...)` меняет wire-level query-контракт; важно сохранить внешнюю MCP-сигнатуру без breaking change.
