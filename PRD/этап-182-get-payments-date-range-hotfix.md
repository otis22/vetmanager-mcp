# Этап 182. `get_payments` date range hotfix

## Контекст

Production feedback `#18` от 2026-06-26: `get_payments` с `date_from/date_to`
и `status=exec` вернул пустой список, хотя `get_revenue_summary` за тот же день
нашёл проведённый платёж и ненулевую выручку.

Пользователь создал свежий счёт/платёж на `devtr6` 2026-06-26 для проверки.

## Проверенные факты

- MCP `get_revenue_summary(date_from="2026-06-26", date_to="2026-06-26",
  mode="received")` вернул:
  - `total_amount="700.00"`;
  - `returned_count=1`;
  - `date_field="create_date"`;
  - filters:
    - `create_date >= "2026-06-26 00:00:00"`;
    - `create_date < "2026-06-27 00:00:00"`;
    - `status = "exec"`.
- MCP `get_payments(date_from="2026-06-26", date_to="2026-06-26",
  status="exec")` вернул `totalCount=0`, `payment=[]`.
- Direct real API probe на `devtr6` подтвердил тот же контракт:
  - current `get_payments` filter shape:
    `create_date >= "2026-06-26"` + `create_date <= "2026-06-26"` +
    `status = "exec"` -> `totalCount=0`;
  - half-open day filter:
    `create_date >= "2026-06-26 00:00:00"` +
    `create_date < "2026-06-27 00:00:00"` + `status = "exec"` ->
    `totalCount=1`, payment `id=258`, amount `700.0000000000`,
    `create_date="2026-06-26 13:15:52"`, `invoice_id=228`.
- `artifacts/api_entity_reference-ru.md` и OpenAPI подтверждают, что
  `payment.create_date` имеет timestamp/date-time семантику
  (`YYYY-MM-DD HH:MM:SS`).
- `tools/invoice.py::get_revenue_summary` уже содержит корректный локальный
  pattern: whole local day as half-open range `[day_start, next_day_start)`.
- `tools/finance.py::get_payments` сейчас использует bare date strings и
  inclusive `<=` для `date_to`, что для timestamp-поля режет весь день после
  полуночи.

## Цель

Сделать `get_payments(date_from=day, date_to=day, status="exec")` пригодным
для drill-down после `get_revenue_summary`: оба инструмента должны находить
одни и те же conducted payments за календарный день/диапазон дней.

## Scope

### In scope

- Изменить date filter semantics `get_payments` для `create_date`:
  - `date_from` -> `create_date >= "{date_from} 00:00:00"`;
  - `date_to` -> `create_date < "{date_to + 1 day} 00:00:00"`.
- One-sided ranges preserve existing optional-argument behavior:
  - only `date_from` -> only lower bound;
  - only `date_to` -> only upper bound as strict next-day boundary;
  - no dates -> no MCP-generated `create_date` filter.
- Добавить validation `date_from <= date_to` после `parse_date_param` only when
  both bounds are present.
- Compute `{date_to + 1 day}` with `datetime.date` + `timedelta`, not string
  manipulation, so month/year/leap-day rollovers are correct.
- Сохранить existing filters:
  - `client_id`;
  - `status`;
  - caller-provided `filter`;
  - caller-provided `sort`;
  - `limit`/`offset`.
- Обновить tool description/docstring для `date_to`: это inclusive local clinic
  date at user level, implemented as exclusive next-day timestamp boundary.
- Define caller `filter` merge contract:
  - caller-provided `create_date` filters remain allowed when `date_from` and
    `date_to` arguments are empty;
  - if caller passes `date_from` or `date_to`, then caller-provided
    `create_date` filters are rejected before upstream request to avoid
    conflicting date constraints.
- Добавить regression tests для exact filter shape и merge с caller filters.
- Добавить opt-in real API note/check для `devtr6` в AssumptionLog после
  implementation только как иллюстративную smoke-проверку текущих данных:
  `get_payments` и `get_revenue_summary` за одну дату должны расходиться не из-за
  filter shape. Конкретный `payment id=258` не является acceptance-критерием,
  потому что внешние тестовые данные нефиксированы.
- После deploy связать production feedback `#18` с fixed known issue либо
  обновить existing known issue, чтобы report не висел `new`.

### Out of scope

- Изменение `get_invoices(date_from/date_to)` legacy `create_date` semantics.
- Добавление новых payment date basis parameters.
- Автоматическая сверка всех payment totals с `get_revenue_summary`.
- Изменение upstream Vetmanager API.
- Создание/изменение счетов или платежей в real API.

## Архитектурное решение

### Проблема

Пользовательская дата в MCP tools означает календарный день/диапазон дней, но
поле Vetmanager `payment.create_date` является timestamp. Bare `YYYY-MM-DD` с
`<=` на верхней границе не включает записи после `00:00:00`, поэтому
однодневный drill-down возвращает пустой список при наличии платежей.

### Контекст и ограничения

- `get_revenue_summary` уже является authoritative path для daily proceeds и
  использует half-open timestamp range.
- `get_payments` нужен как drill-down path по тем же payments.
- `parse_date_param` возвращает date-only строку и сознательно работает в
  локальной clinic date semantics без TZ conversion.
- Vetmanager API принимает filter JSON по `create_date` с timestamp строками.
- Backward compatibility: пользователи ожидают, что `date_to` как дата
  включает весь этот день, а не только полуночь.

### Рассмотренные варианты

1. **Оставить код и уточнить docs.**
   - Плюс: нулевая правка runtime.
   - Минус: сохраняет broken drill-down и противоречит `get_revenue_summary`.

2. **Сделать `date_to` строкой `"YYYY-MM-DD 23:59:59"`.**
   - Плюс: простая inclusive модель.
   - Минус: хуже для fractional seconds и расходится с уже выбранным pattern
     `get_revenue_summary`.

3. **Использовать half-open day range `[00:00:00, next_day 00:00:00)`.**
   - Плюс: совпадает с `get_revenue_summary`; безопасно для fractional seconds;
     привычный backend pattern для timestamp ranges.
   - Минус: меняет raw filter shape и может вернуть больше записей для
     пользователей, которые случайно полагались на старый midnight-only bug.

Выбран вариант 3.

### Выбранное решение

- Добавить в `tools/finance.py` локальные маленькие helpers или вынести общий
  date-range helper, если это не раздует scope:
  - `_parse_date_range`;
  - `_day_start`;
  - `_next_day_start`.
- Для hotfix предпочтителен минимальный локальный helper в `tools/finance.py`,
  чтобы не затрагивать `tools/invoice.py` и не делать cross-module refactor.
  Helper must use `date.fromisoformat(...) + timedelta(days=1)` for next-day
  rollover.
- `get_payments` строит filters так же, как `get_revenue_summary` для
  `mode="received"`.
- Existing user-facing arguments остаются прежними: `date_from`, `date_to`.

### Инварианты

- `date_to` на уровне MCP пользователя остаётся inclusive date.
- API filter верхней границы для timestamp должен быть strict `< next day`.
- `status=exec` и `client_id` продолжают добавляться как server-side filters.
- Caller-provided filters не теряются.
- Caller-provided `create_date` filters are not combined with MCP-generated
  date bounds; that conflict is rejected when date args are present.
- `limit`, `offset`, `sort` не меняют semantics.
- Никакие write tools не добавляются.

### Rollback/fallback

Если upstream неожиданно перестанет принимать timestamp строки в
`payment.create_date`, не откатываться к старому `<= YYYY-MM-DD` поведению как к
нормальному контракту: оно уже воспроизводимо ломает drill-down. Безопасный
операционный fallback для этого hotfix — git revert commit'а Stage 179 +
обычный docker compose deploy rollback, с operator-visible known issue/warning
о potentially incomplete `get_payments` date drill-down до отдельного upstream
compatibility fix. Runtime feature flag не входит в scope. Текущий `devtr6`
probe и `get_revenue_summary` подтверждают, что timestamp filter поддерживается.

## Acceptance criteria

- `get_payments(date_from="2026-06-26", date_to="2026-06-26", status="exec")`
  отправляет filters:
  - `create_date >= "2026-06-26 00:00:00"`;
  - `create_date < "2026-06-27 00:00:00"`;
  - `status = "exec"`.
- `date_from > date_to` rejected before upstream request.
- One-sided ranges:
  - only `date_from` emits only `create_date >= "{date_from} 00:00:00"`;
  - only `date_to` emits only `create_date < "{date_to + 1 day} 00:00:00"`;
  - no dates emits no MCP-generated `create_date` filter.
- If `date_from` or `date_to` is provided together with caller
  `filter[].property == "create_date"`, request is rejected before upstream.
- If no date args are provided, caller-provided `create_date` filters pass
  through unchanged.
- Next-day boundary handles month/year/leap-day rollover.
- Relative dates (`today`, `yesterday`, `-30d`) продолжают резолвиться через
  `parse_date_param`, но filter values становятся timestamp boundaries.
- Existing `client_id`, caller `filter`, `sort`, `limit`, `offset` behavior
  unchanged.
- `get_payments` date filter boundaries stay equivalent to
  `get_revenue_summary(mode="received")` for the same `date_from/date_to`.
- Existing tests for `get_revenue_summary` remain green.
- Targeted tests pass.
- Full suite passes before commit/deploy.
- Post-deploy/prod feedback step: report `#18` no longer remains `new`.

## Тесты

- Update `tests/test_api_contracts_hotfix.py::test_get_payments_uses_create_date_filters_for_march_2026_revenue`
  to expect:
  - `create_date >= "2026-03-01 00:00:00"`;
  - `create_date < "2026-04-01 00:00:00"`.
- Update/add merge test for `client_id` + caller filter:
  - date filters use half-open timestamp boundaries;
  - `client_id` and custom `payment_type` filter preserved.
- Add invalid range test:
  - `get_payments(date_from="2026-06-27", date_to="2026-06-26")` raises
    `date_from must be on or before date_to` and does not call upstream.
- Add one-sided/no-date tests:
  - only `date_from`;
  - only `date_to`;
  - no date args preserves caller `create_date` raw filter.
- Add conflict test:
  - `date_from`/`date_to` plus caller `create_date` filter raises before
    upstream request.
- Add rollover tests:
  - `date_to="2026-12-31"` -> `< "2027-01-01 00:00:00"`;
  - `date_to="2028-02-29"` -> `< "2028-03-01 00:00:00"`.
- Add parity/contract test:
  - for the same `date_from/date_to`, `get_payments` and
    `get_revenue_summary(mode="received")` send equivalent `create_date`
    lower/upper timestamp boundaries.
- Update `tests/test_ergonomic_filters.py::test_get_payments_relative_dates`
  to expect timestamp boundaries after date resolution.
- Optional real API verification after code is green:
  - `devtr6` / `2026-06-26` `get_revenue_summary` and `get_payments` both see
    the fresh payment created by the user.

## Декомпозиция

- 182.1 PRD/research: reproduce on MCP + direct real API, document facts and
  planned fix. <= 2h. — `done`
- 182.2 Implement `get_payments` half-open date range + validation. <= 2h,
  <=150 LOC. — `done`
- 182.3 Regression tests and targeted checks. <= 2h. — `done`
- 182.4 Full checks, audit, review gates, commit/push/deploy. <= 2h. —
  `in_progress`
- 182.5 Production feedback closure for report `#18`. <= 2h. — `todo`

## Architecture Critique

Required before implementation: this changes MCP tool contract and production
financial drill-down behavior. Review should challenge whether the hotfix should
be local to `get_payments` or extracted as shared date-range helper, and whether
any compatibility risk exists for users relying on old date-only filters.

## Review notes

To be filled during implementation workflow:

- Spark PRD review: read-only sandbox hit known `bwrap`/user namespace failure
  before useful file read; stopped and repeated with same model
  `gpt-5.3-codex-spark -s danger-full-access` and review-only prompt. Accepted
  findings: rollback must not normalize old broken midnight-only behavior;
  real API `devtr6` payment id must be illustrative, not acceptance; add parity
  test/contract with `get_revenue_summary`.
- Strong PRD/Architecture Critique: Claude Opus accepted findings for optional
  one-sided date ranges, caller `create_date` filter conflict contract, real
  date arithmetic rollover, and rollback wording without unscope feature flag.
- Spark code review: read-only sandbox hit known `bwrap`/user namespace failure
  before useful completion; stopped and repeated with same model
  `gpt-5.3-codex-spark -s danger-full-access` and review-only prompt. Findings
  were workflow-only: Roadmap/PRD statuses and review notes still reflected
  in-progress release state. No material `get_payments` date-range regression was
  found.
- Strong code review: Claude Opus returned `findings: []`. Non-blocking caveat:
  `get_payments` still does not default `status` to `exec`, so exact
  `get_revenue_summary(mode="received")` drill-down parity depends on the
  documented `status="exec"` argument from production feedback `#18`.
