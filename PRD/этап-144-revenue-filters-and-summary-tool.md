# Этап 144. Revenue filters and summary tool

## Контекст

Stage 143 добавил date filters в `get_payments` и убрал undated payment call из `daily_revenue`, но это закрывает только часть проблемы. Для финансовых ответов вида «выручка за март 2026» LLM всё ещё может:

- взять платежи без `status="exec"`;
- включить черновики/удалённые счета;
- посчитать `amount` вместо `paid_amount`;
- смешать фактически полученные платежи и оплаченные суммы по счетам;
- фильтровать счета по `create_date`, хотя `create_date` — дата создания записи, а `invoice_date` — дата проведения/exec.

Цель этапа: сделать финансовый контракт явным и безопасным для LLM-клиента: базовые tools получают строгие filters, а типовой запрос выручки обслуживается отдельным `get_revenue_summary`.

## Проверенные факты

- `artifacts/vetmanager_openapi_v6.json` описывает `payment.status` как enum `exec`, `save`, `deleted`.
- `artifacts/vetmanager_openapi_v6.json` описывает `invoice.status` как enum `exec`, `save`, `deleted`, `closed`, `archived`.
- `artifacts/api_entity_reference-ru.md` описывает `invoice.paid_amount` как уже оплаченную сумму.
- `artifacts/api_entity_reference-ru.md` описывает `invoice.payment_status` как `none`, `partial`, `full`.
- По продуктовому уточнению пользователя: `invoice.create_date` — когда запись создали, `invoice.invoice_date` — когда счёт провели (`exec`). Для финансового периода по проведённым счетам использовать `invoice_date`.
- `get_invoices` уже поддерживает `payment_status` и `create_date` filters через `date_from/date_to`.
- `get_payments` уже поддерживает `date_from/date_to` по `payment.create_date`.

## Scope

### In scope

1. Добавить `status` в `get_payments`.
   - Допустимые значения: `exec`, `save`, `deleted`.
   - Для revenue defaults и prompts использовать `exec`.
2. Добавить workflow `status` в `get_invoices`.
   - Допустимые значения: `exec`, `save`, `deleted`, `closed`, `archived`.
   - Не смешивать с существующим `payment_status`.
3. Добавить invoice financial date filters:
   - `invoice_date_from`;
   - `invoice_date_to`;
   - оба используют `parse_date_param()`;
   - date-only inputs интерпретируются как локальные даты клиники без timezone conversion;
   - `invoice_date_from` фильтрует `invoice_date >= YYYY-MM-DD 00:00:00`;
   - `invoice_date_to` фильтрует half-open boundary `invoice_date < next_day 00:00:00`, чтобы не терять записи в конце дня и не зависеть от fractional seconds.
4. Сохранить существующие `date_from/date_to` как filters по `create_date`, но явно описать, что это audit/record-created semantics.
   - Если в одном `get_invoices` вызове переданы `date_from/date_to` и `invoice_date_from/invoice_date_to`, rejected before HTTP: смешивать record-created и financial-period semantics нельзя.
   - Если `invoice_date_from/to` переданы без workflow `status`, tool добавляет `status="exec"` как безопасный financial-period default; явный `status` пользователя сохраняется.
5. Добавить amount filters в `get_invoices`:
   - `paid_amount_min`;
   - `paid_amount_max`;
   - `amount_min`;
   - `amount_max`.
6. Валидировать money filters decimal-safe способом без `float`.
   - Денежные totals и breakdown values в response возвращать decimal strings с двумя знаками после точки.
7. Добавить `get_revenue_summary` как основной tool для LLM:
   - `date_from: str`;
   - `date_to: str`;
   - `mode: "received" | "invoiced" | "paid_by_executed_invoices" = "received"`;
   - `include_breakdown: bool = True`;
   - `client_id: int = 0`;
   - `doctor_id` и `clinic_id` остаются out of scope для первой версии summary, чтобы не делать разные field maps для payment/invoice sources без отдельного дизайна.
8. `get_revenue_summary` должен сам применять правильные даты, статусы и суммы:
   - `received`: source `payment`, date `payment.create_date`, filter `status="exec"`, sum `amount`; это единственный cash-revenue mode для вопросов «выручка/получено денег за период»;
   - `invoiced`: source `invoice`, date `invoice.invoice_date`, filter `status="exec"`, sum `amount`; это начислено/проведено по счетам, не cashflow;
   - `paid_by_executed_invoices`: source `invoice`, date `invoice.invoice_date`, filter `status="exec"`, sum current `paid_amount`; это текущая оплаченная часть счетов, проведённых в период, не деньги, фактически полученные в период.
   - Старое имя `paid_by_invoices` не использовать в v1, чтобы не маскировать не-cashflow semantics.
   - Для всех date range filters внутри summary использовать half-open day windows: `from >= YYYY-MM-DD 00:00:00`, `to < next_day 00:00:00`.
9. Добавить bounded pagination с page cap, `truncated` metadata и понятным warning, если данные обрезаны.
   - `page_cap` v1: 20 pages при `page_size=100`, максимум 2000 rows scanned per source.
   - `scanned_count` = количество строк, реально прочитанных и учтённых в сумме до page cap.
   - `returned_count` = количество строк, попавших в применимый source после upstream filters; в v1 совпадает со `scanned_count`, если нет дополнительного client-side filtering.
   - `total_count` = upstream `totalCount`, если он есть и парсится; иначе `null`.
   - `truncated=true`, если `total_count > scanned_count` или page cap reached before confident end-of-data.
   - Pagination sort для summary обязан быть детерминированным по уникальному ключу: `id ASC`.
   - Если API/contract не позволяет применить `id ASC` sort для source endpoint, summary должен fail closed before totals и вернуть/поднять явную ошибку, а не отдавать best-effort financial total.
   - Date filters остаются upstream filters; day breakdown считается по timestamp field из уже просканированных rows.
10. Обновить revenue prompts: предпочитать `get_revenue_summary`, не просить LLM вручную агрегировать raw payments/invoices без статусов.
    - Для пользовательских вопросов «выручка», «получено», «касса», «деньги за период» default mode = `received`.
    - `paid_by_executed_invoices` разрешён только если пользователь явно спрашивает «сколько оплачено по счетам, проведённым за период».
    - Если summary вернул `truncated=true`, prompt/tool description обязаны требовать сообщить, что сумма неполная, и предложить сузить период/фильтр; нельзя представлять partial total как окончательную выручку.
11. Base list tools сохраняют backward-compatible default `status=""`; безопасный financial default `status="exec"` применяется в `get_revenue_summary`, revenue prompts и `get_invoices` вызовах с `invoice_date_from/to`.

### Out of scope

- Сверка бухгалтерской истины между payments, invoices и closingOfInvoices.
- Real accounting reconciliation по возвратам/сторно без подтверждённых API фактов.
- Изменение текущей semantics `get_average_invoice`.
- Автоматическое изменение `date_from/date_to` в `get_invoices` с `create_date` на `invoice_date` без backward-compatible перехода.
- `doctor_id`/`clinic_id` filters в `get_revenue_summary` v1; они требуют отдельной per-mode field map.

## Acceptance Criteria

- `get_payments(status="exec")` отправляет `filter[]` по `status = exec`.
- `get_payments(status="paid")` rejected before HTTP.
- `get_invoices(status="exec")` отправляет `filter[]` по `status = exec`.
- `get_invoices(status="active")` rejected before HTTP.
- `get_invoices(invoice_date_from="2026-03-01", invoice_date_to="2026-03-31")` фильтрует `invoice_date`, не `create_date`, через `invoice_date >= 2026-03-01 00:00:00` and `invoice_date < 2026-04-01 00:00:00`.
- `get_invoices(invoice_date_from="2026-03-01")` без явного `status` добавляет `status="exec"`.
- `get_invoices(date_from="2026-03-01")` сохраняет текущую `create_date` semantics.
- `get_invoices(date_from="2026-03-01", invoice_date_from="2026-03-01")` rejected before HTTP.
- `get_invoices(paid_amount_min="0.01")` отправляет `paid_amount >= 0.01`.
- `get_invoices(paid_amount_max="1000")` отправляет `paid_amount <= 1000`.
- Invalid money filters rejected before HTTP.
- Non-finite money values (`NaN`, `Infinity`, `-Infinity`) rejected before HTTP or before returning summary totals.
- Malformed dates and inverted date ranges are rejected before HTTP for both `date_from/date_to` and `invoice_date_from/invoice_date_to`.
- `get_revenue_summary(date_from="2026-03-01", date_to="2026-03-31", mode="received")` суммирует только payments with `status="exec"` за `payment.create_date`.
- `get_revenue_summary(..., mode="invoiced")` суммирует invoice `amount` только для `invoice.status="exec"` за `invoice.invoice_date`.
- `get_revenue_summary(..., mode="paid_by_executed_invoices")` суммирует current invoice `paid_amount` только для `invoice.status="exec"` за `invoice.invoice_date` and marks the mode as non-cashflow.
- `get_revenue_summary(..., mode="paid_by_invoices")` rejected before HTTP.
- Summary response содержит decimal-string totals, `returned_count`, `scanned_count`, nullable `total_count`, date range, mode, source, applied filters, `page_cap=20`, `page_size=100`, `truncated`, and warnings.
- Summary response при `truncated=true` содержит non-empty warning that totals are partial/incomplete and must not be presented as final revenue.
- Summary pagination uses `sort=[{"property":"id","direction":"ASC"}]`; if deterministic id sort cannot be applied, no authoritative totals are returned.
- `get_revenue_summary` accepts `client_id` for all modes and rejects unsupported future filters before HTTP.
- Prompt tests подтверждают, что revenue prompts предпочитают `get_revenue_summary`, default to `mode="received"` for revenue/cash questions, and warn on `truncated=true`.
- Full Docker suite passes.

## Decomposition

1. Tests for `status` filters on payments and invoices. ≤ 2h / ≤ 150 LOC.
2. Tests for `invoice_date_from/to` and preserving `create_date` filters. ≤ 2h / ≤ 150 LOC.
3. Tests for decimal money filters/date validation and serialization. ≤ 2h / ≤ 150 LOC.
4. Implement filters in `get_payments` and `get_invoices`. ≤ 2h / ≤ 150 LOC.
5. Design and test `get_revenue_summary` response contract. ≤ 2h / ≤ 150 LOC.
6. Implement summary pagination, totals and breakdown metadata. ≤ 2h / ≤ 150 LOC.
7. Update prompts and docs/API notes. ≤ 2h / docs/tests.
8. Full checks, audit, Spark-review, external diff review attempt, commit/push, self-attestation. Workflow step.

## Simplicity Notes

- Prefer adding explicit filters over changing existing parameter semantics.
- Keep `get_revenue_summary` narrow: three modes, fixed source semantics, no reconciliation claims; name non-cashflow modes explicitly.
- Use `Decimal` for money parsing/summing; avoid `float`.
- Keep base list tools backward-compatible: empty `status` means no status filter, but revenue prompts and `get_revenue_summary` must always enforce `exec`.
- Start with day-level breakdown only if it can be done from already fetched rows without extra API calls.
- If page cap is reached, return partial totals with `truncated=true`; never present truncated totals as complete.
