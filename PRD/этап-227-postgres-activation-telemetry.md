# Этап 227. Активационная телеметрия на PostgreSQL

## Контекст и цель

На production PostgreSQL агрегат `ActivationEvent` не выполняется: два отдельно
созданных `coalesce(reason_class, "none")` получают разные bind-параметры в
`SELECT` и `GROUP BY`. Полный scan завершается до записи event-gauge, cache не
сохраняется, а последующая логика age-gauge не достигается. Цель — вернуть
успешный scan и закрепить именно PostgreSQL-регрессию в CI.

## Декомпозиция

1. Вынести одно unlabelled SQLAlchemy-выражение `reason` и использовать его в
   `select` (с label) и `group_by` (без label) (до 20 строк).
2. Добавить PostgreSQL test contour и регрессию полного scan с event- и
   last-request-age gauges (до 150 строк).
3. Запустить Docker checks, аудит, review и зафиксировать решение (до 100 строк).

## Архитектурное решение

Проблема: SQLAlchemy expression identity важна для параметризованного
PostgreSQL `GROUP BY`, однако SQLite разрешает текущий некорректный SQL.

Ограничения: scan вызывается при scrape; cache имеет TTL 60 секунд; метрики не
должны раскрывать PII; production использует PostgreSQL, CI сейчас — SQLite.
`ActivationEvent.reason_class` определён ORM как nullable `String(32)`, не
PostgreSQL enum; поэтому `coalesce(..., "none")` остаётся text expression.

Варианты:

- повторить literal или заменить `coalesce` на Python post-processing: первый
  снова рискован, второй меняет объём и семантику агрегата;
- использовать label-имя в `group_by`: зависит от dialect/настроек SQL;
- создать unlabelled `reason` один раз, label применить только в `select`, а
  expression object передать в `group_by`: минимальная dialect-independent
  правка с одинаковым bind parameter в обеих SQL-частях.

Выбор: один unlabelled `reason` expression в select и group_by, с label только
в select. Отдельный
PostgreSQL CI job поднимает service container и запускает только regression;
обычный SQLite contour остаётся быстрым.

Инварианты:

- event series сохраняют labels/event counts и `none` для NULL;
- успешный scan записывает и event, и account-age gauges и cache;
- тест не зависит от production credentials и не печатает URL/пароль;
- PostgreSQL test создаёт из текущей ORM metadata только свою пустую ephemeral
  database; `reason_class` в ней тот же `String(32)`, что и в runtime model, и
  production schema/migrations не меняются.

Rollback: revert one expression/test/CI job; runtime contract и хранилище не
мигрируются.

Architecture Critique: required — затрагиваются production observability,
PostgreSQL compatibility и CI ownership boundary.

## Scope

- Fix expression reuse in `activation_telemetry.py`.
- Audit remaining computed aggregate/group-by expressions in telemetry modules
  for duplicate parameterized construction.
- Regression test on temporary CI PostgreSQL database.
- CI job that supplies PostgreSQL only to this regression.

## Out of scope

- Изменение метрик, retention, dashboard или production database schema.
- Изменения этапов 223–226 и 228–232.

## Acceptance criteria

1. PostgreSQL выполняет полный scan без GROUP BY error.
2. Test asserts concrete event label/counts, including NULL reason mapped to
   `none`, and a nonempty `account_last_request_age_hours` after scan.
3. A second scan inside 60 seconds uses cache (no full DB refresh).
4. PR CI runs the PostgreSQL regression without secrets and without a skip
   path: local fast/default contours exclude marker `postgres`, while dedicated
   job passes an explicit test-only URL for database `vetmanager_test` and
   invokes the concrete test file.
5. Audit confirms no sibling computed aggregate/group-by expression duplicates
   parameterized SQLAlchemy objects.

## Проверки

- Targeted PostgreSQL regression in Docker CI job.
- Existing default Docker test contour.
- GitHub Actions workflow syntax/static test coverage where applicable.
