# Этап 154. Token expiry pre-notification

## Цель

Дать operator-у и аналитике видеть приближающийся token expiry за 14 / 7 / 1 день до факта, чтобы (а) активный аккаунт не превратился в `dead` молча из-за expired-token, (б) operator мог попросить tenant-а заранее ротировать токен.

## Контекст

Prod-метрика 2026-05-02 (`artifacts/review/2026-04-30-changed-stage-150-152.md` follow-up): `expiring in 7d: 2` для топ-аккаунтов. Сегодня нет ни in-app, ни email уведомлений; молчаливый expiry уже фиксировался как риск в Roadmap 154 (источник этапа).

Существующая инфраструктура:

- `ServiceBearerToken.expires_at` (nullable, tz-aware) и `is_expired()` (line 249 `storage_models.py`).
- `sync_expired_tokens()` (`token_cleanup.py`) — ловит уже-expired tokens и пишет `token_expired` event. Вызывается per-account из `web.py:269` при открытии dashboard.
- `token_usage_logs` table — append-only audit log с `(bearer_token_id, event_type, details_json)` по pattern из `auth_audit.py:108-122`. Используется уже для 9 token-event типов (created/revoked/expired/auth_*).
- `service_metrics.record_business_event(name)` — strict allowlist counter в `_ALLOWED_BUSINESS_EVENTS`. Сегодня содержит 4 events (registered/login/issued/revoked); добавить 5-й.

## Scope

### S1. Detection

Новый helper `scan_token_expiry_warnings(session, *, account_id=None, now=None)` в `token_cleanup.py` (рядом с `sync_expired_tokens`):

- Query: `ServiceBearerToken WHERE status='active' AND expires_at IS NOT NULL AND expires_at > now`. Если `account_id` указан — фильтр.
- Для каждого токена вычислить `days_to_expiry = ceil((expires_at - now).total_seconds() / 86400)` где `now` ВСЕГДА UTC-aware. `expires_at` хранится с timezone (`DateTime(timezone=True)`); если кто-то прислал naive — `_normalize_to_utc` помощник нормализует через `.replace(tzinfo=timezone.utc)` (тот же pattern, что в `ServiceBearerToken.is_expired` line 254-256).
- **Boundary semantics** (важно): `ceil` обеспечивает что токен который истекает РОВНО через N дней даёт `days_to_expiry=N` и считается уже-crossed для threshold=N (включительно сверху). Пример: token at `now + 7.0d` → `days=7` → crossed (7,14); token at `now + 7.000001d` → `days=8` → crossed only (14).
- Crossed-threshold detection: пороги `THRESHOLDS = (1, 7, 14)`. Token «пересёк» threshold N если `days_to_expiry <= N`.
- **Selection rule** (однозначно): из всех порогов N где `days_to_expiry <= N` собрать множество `crossed`. Из `crossed` исключить уже-emitted (см. S2). Если non-empty — emit для **минимального** `min(crossed - emitted)` порога. Примеры:
  - `days_to_expiry=13` → `crossed={14}`, emitted=`{}` → emit `14`
  - `days_to_expiry=5` → `crossed={7, 14}`, emitted=`{14}` → emit `7` (НЕ 1, т.к. 5 > 1)
  - `days_to_expiry=5` → `crossed={7, 14}`, emitted=`{}` → emit `7` (минимальный crossed; 14 не triggered ранее, например первое open dashboard в state)
  - токен с `expires_delta = 0.9d` (примерно 22 часа до expiry; ceil → `days_to_expiry=1`) → `crossed={1, 7, 14}`, emitted=`{7, 14}` → emit `1`
- Псевдокод: `for token in query: cr = {N for N in THRESHOLDS if days <= N}; e = already_emitted_for(token.id, cr); todo = cr - e; if todo: emit(token, min(todo))`.

### S2. Dedup через distinct `event_type` per threshold

Не создаём новую таблицу и не делаем LIKE-substring на JSON (тонкий contract на whitespace в `json.dumps`). Вместо этого — **3 отдельных event_type значения**:

- `TOKEN_EVENT_EXPIRY_WARNING_1 = "token_expiry_warning_1d"`
- `TOKEN_EVENT_EXPIRY_WARNING_7 = "token_expiry_warning_7d"`
- `TOKEN_EVENT_EXPIRY_WARNING_14 = "token_expiry_warning_14d"`

Dedup query — exact match, без LIKE/JSON parsing: `SELECT 1 FROM token_usage_logs WHERE bearer_token_id = :token_id AND event_type = :exact_event_type LIMIT 1`. Существующий index `ix_token_usage_logs_event_type_event_at` (`(event_type, event_at)`) сразу seek'нет на event_type (low cardinality 9+3 enum). Дополнительный композитный index `(bearer_token_id, event_type)` НЕ нужен на текущем масштабе (top-аккаунты ≤10 active tokens × 3 thresholds = ≤30 lookup per dashboard-open) — текущие event_type-row counts мизерные. Если объёмы вырастут (>1000 warning rows) — добавим композитный index в будущем этапе.

`auth_audit.py` получает 3 новых константы; constants списком включаются в любые validation lists в `auth_audit.AUDIT_TOKEN_EVENTS` если такой существует.

**Race condition (acknowledged best-effort)**: два concurrent dashboard opens для одного аккаунта могут оба прочитать «нет prior warning» и каждый emit row → дубликат. Окно — миллисекунды; на текущем traffic-уровне (`0 requests за 7d` per prod metrics 2026-05-02) — практически невозможно. Если понадобится строгий dedup — добавим UNIQUE(bearer_token_id, event_type) constraint в отдельной миграции (для warning event_types). На сегодня: warning duplicates non-critical (operator увидит 2 row вместо 1, понятно что это race), не блокер.

### S3. Emit channel — структурный лог + business event metric

**Source-of-truth = `token_usage_logs` row.** Прочие side-effects (counter, log) — best-effort observability, НЕ источники истины. Если процесс падает между insert row и counter/log — на следующем scan dedup увидит row и не повторит, counter инкрементнется на следующий warning. Acceptable для observability.

Для каждого нового warning:

1. **token_usage_log row** через существующий `add_token_usage_log` с:
   - `event_type=TOKEN_EVENT_EXPIRY_WARNING_<N>` (один из 3 distinct constants).
   - `details = {"account_id": token.account_id, "token_prefix": token.token_prefix, "threshold_days": N, "days_to_expiry": days_to_expiry, "expires_at_utc": expires_at_utc_iso}`
   - `expires_at_utc_iso` строится явно: `expires_at.astimezone(timezone.utc).isoformat()` — гарантирует стабильный UTC ISO 8601 в JSON (не зависит от server tz; `datetime` сам не JSON-serializable, поэтому `.isoformat()` обязателен на конструкции dict до `json.dumps`).
   - **NO email** в details (per privacy contract — `token_prefix` 32 chars из `bearer_token_manager.build_token_prefix` это `sbt_<random>` cryptographically-random material, не содержит email/PII).
2. **`record_business_event(f"token_expiry_warning_{N}d")`** — 3 новых allowed event имён в `_ALLOWED_BUSINESS_EVENTS`: `token_expiry_warning_1d`, `_7d`, `_14d`. Per-threshold visibility для analytics (cardinality 3, безопасно). Counter инкрементируется ТОЛЬКО после успешной insert + commit (т.е. вызывается ПОСЛЕ `await session.commit()`).
3. **`RUNTIME_LOGGER.warning("token_expiry_warning", extra={...})`** структурный лог с теми же полями (account_id, token_prefix, threshold_days, days_to_expiry, expires_at_utc). Никакого raw email.

### S4. Integration points

- Существующий `web.py:269` `await sync_expired_tokens(session, account_id=account_id)` ⇒ добавить рядом `await scan_token_expiry_warnings(session, account_id=account_id)`. Так warnings emit'ятся при каждом dashboard-open.
- Future cron-based global sweep — out of scope (нет cron-инфры; stage 156 покроет synthetic probe + traffic alert, можно туда же добавить); если понадобится оператору раньше — отдельная одноразовая команда `python -m token_cleanup scan_expiry_warnings` достаточна.

### S5. Tests

В новом `tests/test_stage154_token_expiry_warnings.py`:

- `scan_token_expiry_warnings` emit'ит warning для токена с `expires_at = now + 13d` → threshold=14.
- `scan_token_expiry_warnings` НЕ emit'ит повторное warning при следующем вызове (dedup hit).
- При наступлении следующего threshold (token теперь at `now + 6d`) — emit'ит warning для threshold=7 (а не повторно для 14).
- **`days_to_expiry=5`, no prior** → emit threshold=7 (НЕ 1; проверяет селекшн-rule "min crossed not emitted").
- **`days_to_expiry=5`, prior `{14}`** → emit threshold=7.
- **expires_delta < 1d (e.g. 12h, ceil → days_to_expiry=1), prior `{7, 14}`** → emit threshold=1.
- **Boundary** `expires_at = now + 7.0d` точно → `days_to_expiry=7` → threshold=7 crossed (boundary-inclusive сверху).
- **Boundary** `expires_at = now + 7.000001d` → `ceil → 8` → threshold=7 НЕ crossed; only 14 crossed.
- `revoked` token не получает warning (status filter).
- `expired` token (`expires_at < now`) не получает warning.
- Token без `expires_at` (None) — не emit'ит.
- Token с `expires_at = now + 30d` (вне 14d threshold) — не emit'ит.
- `record_business_event("token_expiry_warning_<N>d")` инкрементируется ровно по одному разу за emit для соответствующего N (snapshot `business_events_total`).
- Privacy: token_usage_logs row не содержит `email` ни в keys, ни в values; содержит только account_id, token_prefix, threshold_days, days_to_expiry, expires_at_utc.
- expires_at_utc формат — UTC ISO 8601 with timezone suffix (`+00:00`); тест парсит обратно через `datetime.fromisoformat`.
- `web.py` dashboard route вызывает `scan_token_expiry_warnings` (smoke check that integration call exists — grep на текст файла достаточно для статической верификации).

## Out of Scope

- Email/owner-chat доставка (per Roadmap 154.5; нет канала в проекте на 2026-05-02). **Operator runbook stub**: когда email-канал появится (планируется stage 156+), trigger email из `token_usage_logs WHERE event_type IN ('token_expiry_warning_1d','token_expiry_warning_7d','token_expiry_warning_14d') AND event_at > now() - interval '1 day'` плюс отсутствует follow-up `token_revoked` или новый `token_created` с тем же `account_id`. Query вписывается в существующий triage CLI pattern (см. `scripts/triage_agent_feedback.py`) если понадобится автоматизация.
- Auto-rotation expired tokens (security risk без явного user opt-in).
- Уведомления самому tenant-у через web UI banner (требует UI работы; отдельный этап если нужно).
- Уведомления о approaching `revoked` или `disabled` (revoked/disabled — terminal states, emit'ить уже поздно).
- Threshold > 14 дней (не оперативно; уведомление за месяц до expiry — noise).
- Per-account opt-out (текущая схема — operator-side, не user-facing).
- Изменение схемы — никаких новых таблиц/колонок (используем существующий token_usage_logs).
- Cron-based global sweep (нет cron-инфры; обсудить в stage 156).

## Acceptance Criteria

1. `auth_audit.TOKEN_EVENT_EXPIRY_WARNING_1`, `_7`, `_14` константы определены со значениями `"token_expiry_warning_1d"`, `"token_expiry_warning_7d"`, `"token_expiry_warning_14d"`.
2. `service_metrics._ALLOWED_BUSINESS_EVENTS` содержит все 3 значения: `"token_expiry_warning_1d"`, `"token_expiry_warning_7d"`, `"token_expiry_warning_14d"`.
3. `token_cleanup.scan_token_expiry_warnings(session, *, account_id=None, now=None) -> int` возвращает число emit'нутых warnings; принимает optional `account_id` и `now` для тестирования.
4. **Selection rule** (см. S1): для каждого active токена из всех порогов `(1, 7, 14)` где `days_to_expiry <= N` выбирается множество `crossed`, исключаются уже-emitted, и emit делается для `min(crossed - emitted)`. Тесты для конкретных случаев (см. S5):
   - `days_to_expiry=13`, no prior → emit `14`
   - `days_to_expiry=5`, no prior → emit `7` (НЕ 1, т.к. 5 > 1)
   - `days_to_expiry=5`, prior `{14}` → emit `7`
   - `days_to_expiry=0.9`, prior `{7, 14}` → emit `1`
5. Dedup через exact match `token_usage_logs.event_type IN (TOKEN_EVENT_EXPIRY_WARNING_1, _7, _14)` (без LIKE/JSON parsing). Тест: повторный вызов scan не плодит дубликаты для того же threshold.
6. Privacy: `details` НЕ содержит email; introspection теста проверяет только whitelist полей `{account_id, token_prefix, threshold_days, days_to_expiry, expires_at_utc}`.
7. Filter: revoked / expired / disabled tokens не получают warnings; tokens без expires_at не получают; tokens с `expires_at > now + 14d` не получают.
8. `record_business_event(f"token_expiry_warning_{N}d")` вызывается ровно один раз на каждый emit ПОСЛЕ commit, для соответствующего N (snapshot test проверяет inкремент именно того счётчика, не агрегата).
9. `web.py` account dashboard route вызывает `scan_token_expiry_warnings` рядом с `sync_expired_tokens`; статический grep-test подтверждает.
10. Полный suite `docker compose --profile test run --rm test` — green.
11. Committed diff проходит ревью сторонней моделью (claude-proxy `-p`, 1/1 budget) или явный exhaust с rationale.

## Decomposition

- 154a PRD/review/simplicity gates. ≤2h.
- 154b Const + business event allowlist + scanner helper + tests. ≤2h, ~50 LOC + ~150 LOC tests.
- 154c web.py integration call + smoke-test. ≤30min, ~3 LOC + ~10 LOC test.
- 154d Full suite + audit + commit. ≤1h.
- 154e Diff review (Sonnet + claude-proxy 1/1) + push + AssumptionLog + self-attestation. ≤1h.

Итого ≤6.5 LOC-часов, ~220 LOC прод/тест-кода.

## Risks

- **High-frequency dashboard opens** — каждый раз scan делает по 1 SELECT на (token, threshold) для dedup; аккаунт с 100 active tokens × 3 thresholds = 300 lookup queries per dashboard-open. Mitigation: текущие top-аккаунты ≤10 active tokens → ≤30 queries; существующий `ix_token_usage_logs_event_type_event_at` (per `20260419_000007`) покрывает `WHERE event_type=...` seek (low cardinality, 9 existing event_types + 3 new = 12 distinct values, мизерный subset на event_type). Дополнительный композитный index `(bearer_token_id, event_type)` — НЕ существует; на текущем масштабе не нужен (event_type-rows для warning'ов будут расти медленно — единицы за token-lifetime). Если объём `token_usage_logs` превысит ~50k rows и станет видим в latency — добавим в отдельной миграции.
- **Threshold ordering** — если scan вызван когда token at `days_to_expiry=0.9` (между 1 и 0), мы emit'им warning для threshold=1; следующее обращение через час (still ≤1) — dedup срабатывает. Если вдруг token истечёт до threshold=1 emit (например scan не вызывался) — warning не сработает, но `sync_expired_tokens` сразу обработает expiry. Это acceptable: warning — best-effort retention nudge, не строгий gate.
- **Race condition (best-effort dedup)** — два concurrent dashboard opens одного аккаунта могут оба прочитать «нет prior warning» и emit дубликат. Окно — миллисекунды; current prod traffic 0 req/7d делает практически невозможным. Если когда-либо понадобится строгий dedup — добавим UNIQUE(bearer_token_id, event_type) constraint миграцией (для warning event_types конкретно). На сегодня — acceptable, дубликат нарушает только cosmetic operator-view, не функциональность.
- **Cron нет — emit gated на dashboard-open** — токен пользователя который не открывает dashboard вообще никогда не получит warning. Это known limitation: документировано в operator runbook + Out of Scope; следующий шаг (stage 156) добавит cron-based traffic-alert и можно туда же добавить scheduled scan.

## Rationale для выбранной сложности

**Альтернатива 1: новая таблица `token_expiry_warnings_sent` (token_id, threshold, sent_at) UNIQUE(token_id, threshold)**. Pros: clean dedup index, no LIKE-substring fragility. **Cons (отвергнуто)**:

- Новая Alembic migration + новая ORM модель — overhead ~70 LOC только на schema setup ради dedup, который уже работает через существующий `token_usage_logs`.
- Дублирует семантику `token_usage_logs` (это же audit-log с `event_type` discriminator). Создание отдельной таблицы для одного эвента — over-engineering.

**Альтернатива 2: in-memory dedup через cache** (set из `(token_id, threshold)` пересмотренных warnings, expiry 24h). **Cons (отвергнуто)**:

- Теряется на restart — токен получит дубликаты warnings после deploy.
- Не сериализуется per-process (uvicorn single-worker сейчас, но multi-worker future-proofing — ломаем).
- Нет audit trail — operator не сможет посмотреть «когда мы предупреждали этот токен».

**Альтернатива 3: только структурный лог без token_usage_logs row**. **Cons (отвергнуто)**:

- Логи ротируются (`docker compose logs` default 100MB) — long-term audit невозможен.
- Dedup тогда только через in-memory cache (см. Alt 2).
- Operator не видит warning через psql на `token_usage_logs`.

**Выбранный путь — переиспользование `token_usage_logs` + business_event counter** даёт:

- Zero schema migration overhead.
- Audit trail out of the box (operator query: `SELECT * FROM token_usage_logs WHERE event_type='token_expiry_warning_sent' AND bearer_token_id=X`).
- Dedup через свежее поле `details_json` LIKE — adequate с layered filter `event_type=...`.
- Counter в Prometheus совместим с существующим `business_events_total` для будущих dashboards.
- Dedup через exact match на event_type (3 distinct `_1d`/`_7d`/`_14d`) — без LIKE/JSON parsing/whitespace contracts; existing index `(event_type, event_at)` сразу seek'нет.
- ≤220 LOC total — minimum viable для нашей цели «operator видит approaching expiry заранее».

### Simplicity-eval pass (§4.1) применён

Триггеры проверены:

- **Abstraction без 2+ call-sites**: `scan_token_expiry_warnings` имеет 1 call site (web.py dashboard) сейчас, но контрактно standalone (для cron). Отделение от `sync_expired_tokens` justified — две разные responsibility (terminal-state cleanup vs warning), их объединение размоет семантику.
- **Premature flexibility**: thresholds hardcoded `(1, 7, 14)` вместо config — minimal, можно сделать configurable если operator попросит. Не сейчас.
- **Helper из 1 места**: см. выше.
- **Dual-API surface**: scan_token_expiry_warnings / sync_expired_tokens — РАЗНЫЕ ops, не dual API на одну вещь.
- **Heavy framework где stdlib достаточно**: используем существующий sqlalchemy/auth_audit/service_metrics — ничего нового.

PRD финализирован.
