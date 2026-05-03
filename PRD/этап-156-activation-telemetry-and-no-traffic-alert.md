# Этап 156. Activation telemetry & no-traffic alert

**Дата:** 2026-05-03
**Статус:** draft

## Цель

Сделать видимой ситуацию, когда у активного аккаунта есть рабочий Bearer-токен, но успешных runtime-запросов нет дольше ожидаемого окна. Проблема пришла из prod-метрик 2026-05-02: у топ-аккаунта было `4467` запросов за 30 дней и `0` за 7 дней, а observability не дала отдельного сигнала о drop-off.

## Scope

1. Добавить account-level telemetry на базе уже существующего usage accounting:
   - `ServiceBearerToken.last_used_at` как источник времени последнего успешного bearer runtime-запроса;
   - `Account.status == active` как критерий live account;
   - `ServiceBearerToken.status == active` и не expired/revoked как критерий live token;
   - active `VetmanagerConnection` как критерий, что аккаунт не шумит без настроенной интеграции.
2. Добавить Prometheus gauge:
   - `vetmanager_account_last_request_age_hours{account_id="<id>"}`;
   - label только `account_id`, без email/domain/token prefix.
3. Добавить structured warning log `account_traffic_silent` при достижении порогов 24h и 72h.
4. Обновлять gauge и выполнять no-traffic scan при `/metrics` scrape после успешной auth-проверки `METRICS_AUTH_TOKEN`.
5. Покрыть тестами:
   - успешный bearer runtime-запрос обновляет `ServiceBearerToken.last_used_at`, из которого строится account metric;
   - gauge честно считает возраст последнего запроса;
   - threshold 24h/72h логируется один раз на quiet period;
   - revoked/expired/disabled/no-active-connection accounts не попадают в gauge и не шумят;
   - `/metrics` экспортирует новую серию.

## Out of Scope

- Email, Telegram, Slack или owner-chat уведомления.
- Auto-remediation, авто-ротация токенов, отключение аккаунта.
- Новая таблица или миграция под silence events.
- Synthetic probe, который вызывает read-only MCP tool от имени аккаунта.
- Изменение product-metrics CLI и account hygiene logic.

## Проверенные факты по артефактам и коду

- `auth/bearer.py::resolve_bearer_auth_context` вызывает `token.mark_used(used_at=now)` на successful bearer auth и сохраняет `ServiceBearerToken.last_used_at`.
- `storage_models.py` уже содержит `Account`, `ServiceBearerToken`, `VetmanagerConnection`; новая колонка для Stage 156 не нужна.
- `/metrics` реализован в `web_routes_system.py` и уже защищается optional `METRICS_AUTH_TOKEN`; при неверном токене scrape должен завершаться до DB-scan.
- `service_metrics.py` уже рендерит process-local Prometheus metrics и имеет `reset_service_metrics()` для изоляции тестов.
- `artifacts/observability-runbook-vetmanager-mcp-ru.md` фиксирует, что `/metrics` является основным scrape endpoint, а sensitive labels в метриках недопустимы.

## Дизайн

### 1. Scanner

Новый модуль `activation_telemetry.py`:

```python
async def scan_activation_telemetry(session, *, now=None) -> int:
    ...
```

Поведение:

- выбрать аккаунты, у которых есть:
  - `Account.status == active`;
  - active Vetmanager connection;
  - хотя бы один active bearer token, который не expired/revoked на `now`;
- для каждого аккаунта посчитать `max(ServiceBearerToken.last_used_at)` по его live tokens;
- если `last_used_at` отсутствует для всех live tokens, использовать самый ранний `ServiceBearerToken.created_at` среди live tokens как age anchor: это делает видимым "токен выпущен, но ни разу не использован";
- записать gauge `account_id -> age_hours`;
- если `age_hours >= 24` или `>= 72`, залогировать `RUNTIME_LOGGER.warning("Account traffic is silent.", extra={...})`;
- не логировать один и тот же threshold повторно в рамках одного process lifetime, пока аккаунт снова не станет active по трафику (`age_hours < 24`).

### 2. Metric registry

В `service_metrics.py` добавить:

- `_ACCOUNT_LAST_REQUEST_AGE_HOURS: dict[int, float]`;
- `set_account_last_request_age_hours(values: dict[int, float])`;
- snapshot key `account_last_request_age_hours`;
- Prometheus строки:

```text
# HELP vetmanager_account_last_request_age_hours Hours since last successful bearer runtime request for active accounts.
# TYPE vetmanager_account_last_request_age_hours gauge
vetmanager_account_last_request_age_hours{account_id="123"} 25.5
```

Setter заменяет весь набор account gauges, чтобы accounts, которые стали revoked/dead/no-connection, не оставались stale в process-local registry.

### 3. `/metrics` integration

В `web_routes_system.py` после успешной auth-проверки `/metrics`:

```python
async with get_session_factory()() as session:
    await scan_activation_telemetry(session)
```

Если scan падает из-за storage/SQL error, `/metrics` не должен падать: логируем `activation_telemetry_scan_failed` и возвращаем остальные metrics. Это observability side-effect, не liveness endpoint.

### 4. Privacy

Metric labels:

- разрешено: `account_id`;
- запрещено: email, domain, token prefix, IP, raw token, Vetmanager credentials.

Structured log:

- `event_name="account_traffic_silent"`;
- `account_id`;
- `threshold_hours`;
- `age_hours`;
- `last_request_at_utc` (`null`, если live tokens ещё ни разу не использовались);
- `ever_used`;
- `age_anchor`;
- `live_token_count`.

Email/domain/token prefix не включаются.

## Acceptance Criteria

1. `activation_telemetry.scan_activation_telemetry(session, now=...)` создаёт gauge для active account с active connection и active token.
2. Gauge `vetmanager_account_last_request_age_hours{account_id="..."}` считается из `max(ServiceBearerToken.last_used_at)` по live tokens.
3. Если ни один live token аккаунта ещё не использовался, gauge считается от earliest `ServiceBearerToken.created_at` среди live tokens этого аккаунта.
4. Revoked/expired/disabled tokens и аккаунт без active connection не попадают в gauge.
5. При `age_hours >= 24` пишется structured warning `account_traffic_silent` с `threshold_hours=24`.
6. При `age_hours >= 72` пишется structured warning `account_traffic_silent` с `threshold_hours=72`.
7. Один threshold не логируется повторно в том же quiet period; после нового успешного запроса (`age_hours < 24`) dedup сбрасывается.
8. `/metrics` вызывает scan только после успешной auth-проверки; неверный `METRICS_AUTH_TOKEN` не выполняет DB-scan.
9. Ошибка scan не ломает `/metrics`; пишется `activation_telemetry_scan_failed`.
10. Never-used branch логирует `last_request_at_utc=null`, `ever_used=false`, `age_anchor="token_created_at"`; used branch логирует `ever_used=true`, `age_anchor="last_request_at"`.
11. Tests включают targeted Stage 156 coverage и существующий full suite остаётся зелёным.

## Декомпозиция

- 156a PRD + review gates. ≤2h, docs only.
- 156b `service_metrics` gauge + Prometheus render + tests. ≤2h, ~60 LOC.
- 156c `activation_telemetry.py` scanner + tests. ≤2h, ~100 LOC + tests.
- 156d `/metrics` integration + failure/auth-order tests. ≤2h, ~30 LOC + tests.
- 156e README/runbook update + full checks/audit/reviews. ≤2h.

## Simplicity Review

- Новая storage schema отвергнута: уже есть `ServiceBearerToken.last_used_at` и `ServiceBearerToken.created_at`.
- `TokenUsageStat.last_used_at` отвергнут как источник Stage 156: он дублирует `ServiceBearerToken.last_used_at` для successful auth, но требует лишний join и отдельный fallback path.
- Persistent dedup через `token_usage_logs` отвергнут: событие account-level, а таблица token-level требует искусственно выбирать bearer_token_id; для warning-log достаточно process-local dedup.
- Synthetic probe отвергнут для Stage 156: он требует безопасный read-only tool dry-run от имени аккаунта и может сам создать noise/upstream load; сначала нужна passive telemetry.
- Отдельный metrics registry модуль отвергнут: `service_metrics.py` уже является single entry point для process-local metrics.

## Риски

- Process restart может повторно залогировать already-silent account. Это приемлемо: warning не является durable alert state, а повтор после рестарта полезен оператору.
- Multi-worker scrape может дать до N одинаковых `account_traffic_silent` warning за quiet period, потому dedup process-local. Это принято для Stage 156: production сейчас не фиксирует multi-worker запуск в compose/deploy, Redis-backed cluster-wide dedup добавит внешнюю зависимость и новый failure mode ради advisory log. Если появится шум в runtime logs, следующий этап может заменить process-local dedup на Redis `SET NX EX`.
- `/metrics` scrape теперь делает лёгкий DB read. Query ограничен account/token stats и выполняется только после metrics auth. Если появятся сотни/тысячи аккаунтов, можно вынести scan в background job или product metrics command.
- `account_id` label имеет cardinality по числу аккаунтов; на текущем масштабе это безопасно и не раскрывает email/domain.
