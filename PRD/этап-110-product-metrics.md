# Этап 110. Product metrics — ad-hoc report + business events counter

## Цель

Дать владельцу продукта (self-hosted, один смотрящий) быстрый ответ на вопросы:
«Сколько сейчас живых аккаунтов? Кто мёртв? Сколько выдано токенов и кто
использует сервис?». Без Grafana, без нового docker-сервиса, без OLAP.

Решение: standalone скрипт `scripts/product_metrics_report.py` читает уже
существующие таблицы (`Account`, `ServiceBearerToken`, `TokenUsageStat`,
`TokenUsageLog`, `VetmanagerConnection`), агрегирует по аккаунтам и печатает
отчёт в Markdown. Вызывается через skill `/product-metrics`, который идёт
по ssh на prod и форматирует ответ в чате.

Дополнительно: business-event counter в `service_metrics.py` — копит историю
для будущего Grafana-варианта без доп. работы сейчас.

## Scope

### 110.1 Скрипт `scripts/product_metrics_report.py` (~180 LOC)

CLI:
- `--window=30d` (default) — окно для «live» / «dead» классификации
- `--format=markdown|json` (default: markdown)
- `--top-n=10` (default) — сколько top-accounts показывать
- Дата «сейчас» — `datetime.now(timezone.utc)` (параметр `--now-override`
  для тестов, не для production)

Метрики (все scoped по `Account`):

**Accounts (6 counters):**
- `accounts.total` — всего
- `accounts.new_24h` / `new_7d` / `new_30d` — по `Account.created_at`
- `accounts.live` — has `TokenUsageStat.last_used_at > now - window`
- `accounts.dead` — `Account.created_at < now - 30d` AND
  (no tokens OR all tokens `last_used_at < now - 30d` OR NULL)
- `accounts.no_tokens` — зарегистрировались, но не выпустили токен
- `accounts.no_connection` — без активного VetmanagerConnection

**Tokens (5 counters):**
- `tokens.total_active` — `status=active` AND (`expires_at IS NULL OR > now`)
- `tokens.expiring_in_7d` — `status=active AND expires_at BETWEEN now AND now+7d`
- `tokens.issued_24h` — `TokenUsageLog` events `token_created` за последние 24h
- `tokens.revoked_24h` — events `token_revoked` за 24h
- `tokens.expired_auto_24h` — events `token_expired` (auto-sync) за 24h

**Requests (3 summaries):**
- `requests.total_24h` / `total_7d` / `total_30d` — COUNT(`TokenUsageLog`
  where `event_type=token_auth_succeeded`) за окно
- `requests.top_accounts` — top-N accounts by 30d request count
  (через join с `TokenUsageStat` или sum по `TokenUsageLog`)

**Failures (breakdown by reason, 24h and 7d):**
- `rate_limited`, `revoked`, `expired`, `disabled`, `ip_denied`, `no_scopes`, `no_connection`

**Dead account list (для отдельной таблицы):**
- Account rows where `created_at < now - 30d` AND no requests in 30d.
  Columns: `account_id`, `email` (masked: `ma***@ex***.com`), `created_at`,
  `last_request_at` (может быть NULL), `token_count`.

### 110.2 Business events counter

`service_metrics.record_business_event(event_name: str)` — `DefaultDict[str, int]`.
4 call-sites (уже подготовлены 107-м этапом — только обернуть):
- `web_routes_auth.register_submit` — success
- `web_routes_account.issue_service_bearer_token` wrapper — success
- `web_routes_account.revoke_service_bearer_token` wrapper — success
- `web_routes_auth.login_submit` — success (`web_login_succeeded` event_name
  уже логируется)

Counter значения попадают в `snapshot_service_metrics()` и
Prometheus-вывод через существующий endpoint `/metrics`. Скрипт
`product_metrics_report` может дополнительно читать их для cross-check,
но primary source — БД (durable).

### 110.3 Тесты

`tests/test_stage110_product_metrics.py`:
- Fixture: создаёт `prepared_web_db` + вставляет 5 accounts, 8 tokens,
  N-usage-logs в разных временных окнах.
- Test matrix:
  - `test_accounts_counters` — проверяет `total`/`new_24h`/`new_7d`/`new_30d`.
  - `test_live_dead_classification` — 3 аккаунта: live (req 3d ago),
    dead (req 40d ago), never-used (30d registered, 0 requests).
  - `test_tokens_counters` — active/expiring/issued/revoked/expired breakdowns.
  - `test_requests_top_accounts` — 3 accounts, разный request_count,
    top-2 возвращается в правильном порядке.
  - `test_failures_breakdown_24h_and_7d` — 3 log entries на разные reason'ы.
  - `test_markdown_output_renders_sections` — smoke-check что все
    секции присутствуют в выводе.
  - `test_json_output_schema_stable` — ключи в JSON зафиксированы.
  - `test_email_masking_in_dead_account_list` — `user@example.com` →
    `us***@ex***.com`.

Тесты на `record_business_event`: unit-test увеличения counter + snapshot.

### 110.4 Skill `.claude/commands/product-metrics.md`

Instructions для агента:
- По умолчанию зовёт:
  `ssh root@212.193.59.219 "cd /opt/vetmanager-mcp && docker compose exec -T mcp python scripts/product_metrics_report.py --format=markdown"`
- Опциональные args: `--window=7d`, `--top-n=20`
- Форматирует вывод в chat: заголовки `##`, tables, списки dead accounts
- Если stdout содержит ошибку — покажи трассу и подскажи проверить
  `/healthz`

### 110.5 README section

Короткий раздел «Product metrics»: как вызвать skill, что видишь, где
сырые данные (`scripts/product_metrics_report.py` + `/metrics`).

## Non-scope

- Persistent daily snapshots таблица — подождёт до accounts > 100 или до
  запроса на trends
- Grafana / Prometheus gauges — ждут триггер (см. обсуждение уровней)
- HTML dashboard endpoint — ждут второго смотрящего
- Cron/scheduler — скрипт on-demand
- Cohort-analysis / retention — overkill для single-operator
- Auth на скрипт — SSH-доступ и prod shell — уже gated

## Acceptance

1. `docker compose --profile test run --rm test tests/test_stage110_product_metrics.py` — все тесты зелёные.
2. `docker compose exec mcp python scripts/product_metrics_report.py` на prod — возвращает корректный Markdown за < 2 секунды на текущей БД.
3. `/product-metrics` skill вызывает скрипт и показывает отчёт в чате.
4. `snapshot_service_metrics()["business_events_total"]` содержит 4
   известных event_name после тестового прогона каждого flow.
5. Codex review: 0 findings после 1 итерации.
6. 665 → 665+ tests passed.

## Декомпозиция

| # | Подзадача | LOC |
|---|---|---|
| 110.1 | `scripts/product_metrics_report.py` + SQL queries | ~180 |
| 110.2 | `service_metrics.record_business_event` + 4 call-sites | ~30 |
| 110.3 | Tests | ~150 |
| 110.4 | `.claude/commands/product-metrics.md` skill | ~30 |
| 110.5 | README section | ~15 |

Total: ~405 LOC в 5 файлах. В рамках one-session refactor по §3 CLAUDE.md.

## Simplicity evaluation (§4.1)

Прошёл 8 triggers:

1. **Abstraction без 2+ call-sites** — нет. Скрипт — один caller.
   `record_business_event` уже имеет 4 call-sites → OK.
2. **Premature flexibility** — `--format=json` есть на случай future
   piping, но `--format=markdown` default; overhead 15 LOC.
3. **Indirection > 2 hops** — skill → ssh → docker exec → python. Это
   один hop ssh-over-shell, не абстракция.
4. **Dual-API surface** — нет. Single entrypoint.
5. **Paired sync mechanisms** — нет. Data только читается из БД.
6. **State machine > 3 states** — не применимо.
7. **Lazy imports** — standalone script, module-level imports.
8. **Heavy framework** — просто SQLAlchemy (уже есть), Jinja2 не нужен
   (простые f-string Markdown).
9. **Helper из 1 места** — `_format_markdown_report()` и `_format_json_report()`
   каждый из 1 места, но разделение по formatter = single-responsibility,
   не over-abstraction.

**Rationale для выбранной сложности**: альтернатива «inline всё в один
плоский print'ящий блок» даёт ~250-line procedure, плохо тестируется
в изоляции. Текущая декомпозиция (query functions + format functions +
CLI) чуть длиннее, но каждая функция testable. Decision: OK.

## План работы

1. **Test-first**: 110.3 — написать тесты с fixture данными, они
   падают (красные).
2. **Implement 110.1**: скрипт + queries до зелёных тестов.
3. **Implement 110.2**: `record_business_event` + 4 call-sites.
4. **Implement 110.4 + 110.5**: skill + README.
5. Full suite + Codex review + commit + self-attestation checklist + push
   + deploy + ручной smoke-test `/product-metrics` на prod.
