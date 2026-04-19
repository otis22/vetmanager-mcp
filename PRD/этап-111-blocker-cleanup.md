# Этап 111. Blocker cleanup + metric gaps

## Цель

Закрыть 2 blocker + 2 small high, выявленные super-review 2026-04-19 + Codex arbitration. Фокус на быстрых, independent, low-risk изменениях.

## Scope

### 111.1 F1 — `/metrics` endpoint auth gate (BLOCKER)

**Проблема:** `web_routes_system.py::metrics_export` экспортирует `vetmanager_business_events_total{event=...}` + `auth_failures_total{source=...,reason=...}` на публичный `/metrics` без auth. Nginx проксирует `/` без allow/deny. External scraper каждые 15s получает cadence регистраций/логинов/выпуска токенов — business intelligence leak + timing side-channel для credential-stuffing.

**Решение:**
1. Env var `METRICS_AUTH_TOKEN` (optional). Когда задан — endpoint требует `Authorization: Bearer <token>` или возвращает 403. Когда не задан — backward-compat (endpoint открытый, для dev/self-hosted). Пользователь в prod обязан установить.
2. `scripts/init_server.sh` добавить nginx `location = /metrics { allow 127.0.0.1; deny all; }` **перед** `location /`. Defence-in-depth — скрытый endpoint для external scraping.
3. Тест: 403 без token, 200 с token, 200 без обоих когда env не задан.

**LOC estimate:** ~30 (web_routes_system.py) + ~5 (init_server.sh) + ~40 (tests) = ~75.

### 111.2 F3 — composite index (BLOCKER)

**Проблема:** `scripts/product_metrics_report.py::collect_metrics` делает 10 serial queries (7× `_count_events` + 3× `_failure_breakdown`), все `WHERE event_type=X AND event_at>=Y`. `alembic/versions/20260321_000001_bearer_service_baseline.py:62-72` создаёт таблицу без композитного индекса. На prod при 100k+ rows — full table scans.

**Решение (минимальное для закрытия blocker):**
1. Alembic миграция `20260419_000007_token_usage_logs_event_index.py`:
   ```python
   op.create_index("ix_token_usage_logs_event_type_event_at",
                   "token_usage_logs", ["event_type", "event_at"], unique=False)
   ```
   Существующие queries **автоматически** используют этот индекс (SQLite и Postgres planners — оба выбирают composite index когда matching WHERE predicate `event_type = X AND event_at >= Y`). Query-text refactor не нужен для index-use.
2. Тест: миграция применяется/откатывается чисто; `SELECT sql FROM sqlite_master WHERE type='index' AND name='ix_token_usage_logs_event_type_event_at'` возвращает row после upgrade.

**Decision log:** Query-collapse в один GROUP BY (10→1 query) перенесён в stage 112 как performance-optimization после того как index покрыл основную проблему scaling. Причина: query refactor потребует изменить schema return value + migrate 13 stage-110 тестов; ROI не оправдывает риск в blocker cleanup.

**LOC estimate:** ~40 (migration) + ~20 (tests) = ~60.

### 111.3 F5 — login lockout metric (HIGH)

**Проблема:** `web_routes_auth.py:198-210` (login RateLimitError branch) возвращает 429 без вызова `record_auth_failure(source="web_login", reason="rate_limited")`. Stage 107.3 добавил это для register, забыл login. Credential-stuffing attacker, срабатывающий на login lockout, невидим в Grafana.

**Решение:**
1. Одна строка `record_auth_failure(source="web_login", reason="rate_limited")` перед `return html_response(..., 429)` в `web_routes_auth.py:198`.
2. Тест: POST `/login` 11+ раз за 15 мин с одним email → `snapshot_service_metrics()["auth_failures_total"][("web_login", "rate_limited")]` >= 1.

**LOC estimate:** 1 строка + ~25 тест = ~26.

### 111.4 F6 — record_business_event silent-drop fix (HIGH)

**Проблема:** `service_metrics.py:72-86 record_business_event` silent-drop для unknown event_name (для защиты от cardinality blow-up). Typo в будущем call-site (`accont_registered` вместо `account_registered`) молча инкрементирует nothing; operator видит 0 в Grafana, расследует несуществующий incident.

**Решение:**
1. Добавить `RUNTIME_LOGGER.error("record_business_event: unknown event_name dropped", extra={"event_name": "business_event_unknown", "dropped_name": event_name})` перед `return` (line 84).
2. Тест: `record_business_event("typo")` → ERROR log emitted; counter `_BUSINESS_EVENTS_TOTAL` не инкрементирован.

**LOC estimate:** ~4 строки + ~20 тест = ~24.

## Non-scope

- **F7 (billing hardening)** — перенесён в stage 113 "Resilience completeness" (~2h сам по себе, logically fits there).
- Полная замена silent-drop на `Literal[...]` / `Enum` на call-site — nice-to-have, отложено (требует миграции 4 call-site и type-checker).
- Разделение registries (internal vs public `/metrics`) — альтернатива F1 fix; не нужна при наличии auth gate.

## Acceptance criteria

1. `/metrics` без `METRICS_AUTH_TOKEN`: 200 (backward compat).
2. `/metrics` с `METRICS_AUTH_TOKEN=xxx`:
   - без `Authorization` header → 403
   - `Authorization: Bearer xxx` → 200 + Prometheus body
   - `Authorization: Bearer wrong` → 403
3. `scripts/init_server.sh` содержит `location = /metrics { allow 127.0.0.1; deny all; }`.
4. Alembic миграция `20260419_*_token_usage_logs_event_index.py` применяется успешно; downgrade обратим; composite index присутствует в `sqlite_master` после upgrade.
5. Test `test_login_rate_limit_records_auth_failure` зелёный.
6. Test `test_record_business_event_unknown_logs_error` зелёный; counter не инкрементирован для typo.
7. Все существующие 678 tests остаются зелёными.
8. Codex review: 0 critical adequate findings после ≤2 итераций.

## Декомпозиция

| # | Подзадача | LOC | Файлы |
|---|---|---|---|
| 111.1 | /metrics auth gate | ~75 | `web_routes_system.py`, `scripts/init_server.sh`, `tests/test_metrics_auth.py` (new) |
| 111.2 | composite index (migration only) | ~60 | `alembic/versions/*token_usage_logs_event_index.py` (new), `tests/test_stage111_blocker_cleanup.py` |
| 111.3 | login rate-limit metric | ~26 | `web_routes_auth.py`, `tests/test_stage111_login_metrics.py` (new) |
| 111.4 | silent-drop ERROR log | ~24 | `service_metrics.py`, `tests/test_stage111_login_metrics.py` |

Total: ~185 LOC across 6 файлов. В рамках one-session refactor.

## Simplicity evaluation (§4.1)

Прошёл 8 triggers:

1. **Abstraction без 2+ call-sites** — нет. Каждое изменение прямое.
2. **Premature flexibility** — `METRICS_AUTH_TOKEN` optional вместо required = backward compat для self-hosted deploy; НЕ speculative (пользователь явно просил avoid breaking changes без migration).
3. **Indirection > 2 hops** — нет. `metrics_export` → check header → return.
4. **Dual-API surface** — нет. Single endpoint с conditional auth.
5. **Paired sync mechanisms** — нет.
6. **State machine > 3 states** — нет.
7. **Lazy imports** — нет. Всё на module level.
8. **Heavy framework где stdlib достаточно** — нет. `os.environ.get` + `request.headers.get`.
9. **Helper вызывается из 1 места** — 111.2 вводит `_count_events_grouped` (1 caller) вместо `_count_events` (многоразовый), но выигрыш в перфе оправдывает single-caller abstraction. Оригинальный `_count_events` удалить, не оставлять.

**Rationale для выбранной сложности:** все 4 подзадачи independent, могут быть реализованы параллельно или sequentially без shared state. Тесты изолированы per subtask. Risk регрессии минимальный.

**Альтернативы рассмотренные:**
- A1. Полностью убрать silent-drop (просто raise) — отклонено: ломает production если typo уже существует в call-site (reliability regression).
- A2. Отдельный `_BUSINESS_EVENTS_REJECTED_TOTAL` counter — отклонено как extra scope; ERROR log достаточен на первой итерации.
- A3. Один Prometheus request per endpoint в F3 (не collapse) — отклонено: acceptance криtierion requires index + query reduction.

## План работы

1. **Подзадача 111.2 сначала** (самый большой риск — DB migration): написать тесты, migration, refactor queries, прогнать test suite.
2. **Подзадача 111.1**: env var + header check + tests + nginx config.
3. **Подзадача 111.3 + 111.4** параллельно (мелкие).
4. Полный прогон `docker compose --profile test run --rm test`.
5. Codex review с diff + PRD inline.
6. Исправление адекватных findings → re-run tests → re-review (max 2 итерации).
7. Self-attestation checklist.
8. Commit + push.
