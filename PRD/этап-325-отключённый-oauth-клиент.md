# Этап 325. Отключённый OAuth-клиент продолжает работать

## Цель

Устранить подтверждённые расхождения между OAuth и service bearer: отключение
OAuth-клиента должно немедленно закрывать runtime-доступ и каталог прав,
OAuth access token должен расходовать тот же runtime per-token бюджет, а база
должна гарантировать одно активное подключение Vetmanager на аккаунт. Публичный
endpoint MCP должен вычисляться одинаково для сервера, OAuth и onboarding.

## Проверенные факты

### 325.1 — F14

- `OAuthClient.status` существует, ограничен `active`/`disabled`; DCR создаёт
  клиента активным; миграция создаёт колонку `NOT NULL`, поэтому legacy `NULL`
  исключён. В проекте нет кабинета, скрипта или route, переключающего
  его в `disabled`: kill switch сейчас доступен только оператору БД.
- `runtime_auth._resolve_oauth_runtime_credentials` и
  `peek_runtime_scopes` читают access token → grant → account → connection, но
  не читают `OAuthClient`. Поэтому F14 для runtime и scope-peek подтверждён.
- Refresh-flow уже вызывает `_require_active_oauth_client`; выключенный клиент
  не получает новую пару токенов. Это часть F14 опровергнута кодом.
- Live-access accounting уже join-ит `OAuthClient` и требует `active`, поэтому
  runtime и accounting противоречат друг другу.

### 325.2 — F15

- Service bearer вызывает `auth.rate_limit.BEARER_RATE_LIMITER.check_or_raise`
  с `ServiceBearerToken.id`; backend namespace — `bearer`, ключ — строковый id.
  OAuth runtime этого вызова не делает, поэтому F15 подтверждён.
- OAuth budget должен быть на `OAuthGrant.id`, а не access token: refresh
  ротация не должна обнулять уже израсходованный лимит. Общий limiter сохранит
  алгоритм, конфигурацию и текст/тип `RateLimitError`, но использует type-aware
  key `oauth_grant:<id>`.

### 325.3 — F9

- `_save_connection` сериализует только задачи одного Python-процесса через
  `_ACCOUNT_SAVE_LOCKS`; `SELECT ... FOR UPDATE` не блокирует отсутствие active
  строк. Частичного уникального индекса в модели и миграциях нет. F9
  подтверждён.
- Активные подключения создаются после перевода прежних в `disabled`; частичный
  уникальный индекс `(account_id) WHERE status = 'active'` допускает любые
  disabled строки (включая известную production-картину: 7 disabled и 1 active
  у аккаунта 6). На тестовой базе перед миграцией будет явно проверено, что
  дубликатов active нет; production-данные напрямую не читаются этой задачей.

### 325.4 — F23

- OAuth normalizes repeated and trailing path separators; server передаёт raw
  `MCP_PATH`; landing и account onboarding сохраняют separators, но валидируют
  URL строже OAuth. Например, `//custom//mcp/` даёт OAuth `/custom/mcp`, server
  `//custom//mcp/`, onboarding `//custom//mcp/`; `custom/mcp` даёт OAuth
  fallback `/mcp`, server `custom/mcp`, onboarding fallback `/mcp`.
- F23 подтверждён. Текущие production defaults должны остаться
  `https://vetmanager-mcp.vromanichev.ru/mcp`; тест использует дефолты, не
  читая и не публикуя `.env`.

## Решение

1. В `runtime_auth` запрашивать клиента grant-а и требовать
   `OAuthClient.status == active`; тот же fail-closed check добавить в scope-peek.
   Не менять refresh-flow: он уже защищён. Новый отказ остаётся существующим
   OAuth `invalid_token` для runtime и `None` для catalogue.
2. В shared limiter добавить явный subject key (`service_bearer:<id>` и
   `oauth_grant:<id>`) при неизменных namespace, лимите и `RateLimitError`.
   OAuth runtime вызывает тот же `BEARER_RATE_LIMITER`; не добавлять OAuth audit
   schema, поскольку OAuth success уже журналируется, а parity ограничена
   одинаковым отказом и бюджетом.
3. Добавить модельный `Index` и Alembic migration с PostgreSQL/SQLite partial
   unique index. При `IntegrityError` в `_save_connection` откатывать insert
   через SAVEPOINT и возвращать явный конфликт, не чужое подключение; не
   полагаться на process-local lock как на гарантию. Миграция перед созданием индекса проверяет
   отсутствие duplicate active rows и падает с безопасной диагностикой.
4. Вынести validated `PublicEndpointConfig` в `oauth_metadata`; server и два
   HTML caller-а используют его. Никакие значения из `.env` не логируются.

## Декомпозиция

1. **325.1 (≤150 LOC):** красные тесты runtime/scope-peek и refresh disabled
   client, затем минимальная проверка клиента.
2. **325.2 (≤150 LOC):** красный parity test OAuth runtime budget и type-aware
   limiter key, затем shared limiter call.
3. **325.3 (≤150 LOC):** migration/model test и two-session race against empty
   active set, затем partial unique index и `IntegrityError` handling.
4. **325.4 (≤150 LOC):** matrix normalization tests for defaults, slash and
   scheme inputs, затем единый provider и consumers.

## Acceptance criteria

1. Disabled OAuth client rejects existing access token in runtime and returns
   no tailored catalogue; refresh returns `invalid_client` and issues no pair.
   После возврата `active` доступ живого токена восстанавливается без re-auth.
2. OAuth grant requests above `BEARER_RATE_LIMIT_*` receive the same
   `RateLimitError`/retry semantics as service bearer; refresh не сбрасывает
   бюджет. Лимит проверяется против наблюдаемого пика OAuth (226/сутки).
3. Database accepts disabled history plus one active connection, rejects a
   second active row from independent sessions, and migration is reversible.
4. Server route, OAuth resource validation/metadata and landing/account MCP
   URL use exactly one normalized endpoint configuration; default public URL
   is unchanged.
5. Нестандартный `MCP_PATH` получает fallback с structured log; default route
   unchanged. Each regression guard is shown red by a targeted temporary break and green
   after restoration; full mock suite is green and opt-in real suite is run
   when its test contour is configured.

## Out of scope

- UI/API for an operator to disable OAuth clients;
- retroactive revocation or deletion of issued OAuth tokens;
- changes to OAuth DCR/token-endpoint IP limiter;
- changes to Vetmanager upstream API tools.

## Production gate и post-deploy

Push запрещён до результата супервизорской SQL-предпроверки active duplicates.
Перед migration оператор выполняет:
```sql
SELECT account_id, count(*) AS active_count
FROM vetmanager_connections
WHERE status = 'active'
GROUP BY account_id
HAVING count(*) > 1;
```
После Deploy Prod супервизор через 5–10 минут сверяет новые строки
`token_auth_succeeded` с `oauth_access_token_id IS NOT NULL` и OAuth labels
`vetmanager_auth_failures_total`; public MCP smoke в GitHub Deploy — отдельное
подтверждение доступности новой авторизации.

## Оценка простоты

Один canonical endpoint provider и один existing limiter — меньшая поверхность,
чем новые wrappers или OAuth-specific limiter/audit tables. Partial unique index
— единственная process-independent гарантия; advisory locks и новый account
locking protocol сложнее и не нужны после DB constraint. Никакой новой
конфигурации кроме существующих limiter env не вводится.
