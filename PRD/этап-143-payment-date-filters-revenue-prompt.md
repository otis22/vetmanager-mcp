# Этап 143. Payment date filters and revenue prompt hotfix

## Контекст

Источник: обращение пользователя 2026-04-24: агент на запрос «посчитать выручку за март 2026 года» получил платежи за декабрь 2015. Анализ кода показал, что `get_payments` не принимает `date_from`/`date_to`, а prompt `daily_revenue` предлагает `get_payments(limit=100, sort=[...])` без date filter.

Цель этапа: сделать кассовую выручку по платежам за период корректно запрашиваемой через MCP и убрать prompt, который подталкивает LLM к недатированному payment-запросу.

## Проверенные факты

- `tools/finance.py::get_payments()` сейчас принимает `limit`, `offset`, `client_id`, `sort`, `filter`; date helper params отсутствуют.
- `prompts.py::daily_revenue()` вызывает `get_invoices(date_from=date, date_to=date, limit=100)` и затем предлагает `get_payments(limit=100, sort=[{'property':'id','direction':'DESC'}]) if needed`, то есть без фильтра даты.
- `artifacts/vetmanager_openapi_v6.json` для `/rest/api/payment/` поддерживает стандартные `limit`, `offset`, `sort`, `filter`.
- `artifacts/api_entity_reference-ru.md` описывает `payment.create_date` как дату совершения платежа.
- `tools/invoice.py::get_invoices()` уже использует `parse_date_param()` и `filter[]` по `create_date`; этот pattern можно переиспользовать для payments.

## Scope

### In scope

1. Добавить `date_from` и `date_to` в `get_payments`.
2. Для `date_from` добавлять `filter[]` условие `create_date >= <YYYY-MM-DD>`.
3. Для `date_to` добавлять `filter[]` условие `create_date <= <YYYY-MM-DD>`.
4. Сохранить существующие `client_id`, `sort`, `filter`, `limit`, `offset` semantics; date filters должны merge-иться с caller-provided filters.
5. Если caller-provided `filter` уже содержит `create_date`, helper date filters добавляются как дополнительные constraints (intersection semantics), как в существующем `get_invoices` pattern; конфликтующие фильтры не валидируются локально.
6. Обновить `daily_revenue` prompt так, чтобы платежи за день/период запрашивались с теми же date filters, а не global latest/first payments.
7. Добавить regression tests на март 2026 и relative dates.
8. Обновить API notes/docs только если меняется user-facing contract.

### Out of scope

- Новый агрегирующий tool `get_revenue`.
- Автоматическая пагинация всех payments за период.
- Изменение semantics `get_invoices` или `get_average_invoice`.
- Real API e2e без `TEST_DOMAIN`/`TEST_API_KEY`.

## Acceptance Criteria

- `get_payments(date_from="2026-03-01", date_to="2026-03-31")` отправляет `/rest/api/payment` с `filter[]` по `create_date >= 2026-03-01` и `create_date <= 2026-03-31`.
- `get_payments(date_from="-30d", date_to="today")` резолвит relative dates через существующий `parse_date_param()`.
- `get_payments(client_id=42, date_from="2026-03-01")` сохраняет `client_id` filter и добавляет date filter в тот же `filter[]`.
- Caller-provided `filter` не теряется при добавлении date filters; если caller уже передал `create_date`, дополнительные date helper filters применяются как intersection.
- Tool schema/list metadata exposes `date_from` and `date_to` for `get_payments`.
- `daily_revenue` prompt больше не содержит `get_payments(...)` без `date_from`/`date_to`; prompt явно использует один и тот же период для invoice и payment requests.
- Regression test на сценарий «выручка за март 2026» проверяет, что payment-запросы не уходят без `create_date` filter.
- Targeted tests and full Docker suite pass.

## Decomposition

1. Tests for `get_payments` absolute date filters, merge with `client_id`, merge with caller filters. ≤ 2h / ≤ 150 LOC.
2. Tests for relative dates, tool schema metadata, and `daily_revenue` prompt not suggesting undated payments. ≤ 2h / ≤ 150 LOC.
3. Implement `get_payments(date_from/date_to)` with existing `parse_date_param()` and filter primitives. ≤ 2h / ≤ 150 LOC.
4. Update prompt and docs/API notes if needed. ≤ 2h / docs only.
5. Full checks, audit, Spark-review, external diff review, commit/push, self-attestation. Workflow step.

## Simplicity Notes

- Reuse the existing `get_invoices` date-filter pattern; do not introduce a new revenue abstraction for this hotfix.
- Keep date bounds as date strings for parity with `get_invoices`; no timezone conversion or end-of-day expansion without real API evidence.
- Do not auto-page all payments because the current list-tool contract is explicit pagination with `limit`/`offset`.
