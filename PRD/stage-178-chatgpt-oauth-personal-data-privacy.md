# Stage 178. ChatGPT OAuth personal-data privacy mode

## Статус

Done.

## Контекст

Stage 173-177 добавили ChatGPT OAuth connect flow: DCR, authorize consent,
authorization code exchange, refresh rotation, access preset selection и
инструкции для подключения. Bearer-токены уже имеют отдельный флаг
`is_depersonalized`, который не меняет scopes, но заставляет centralized
sanitizer скрывать ФИО, телефоны, email и адреса в tool result.

Пробел: ChatGPT OAuth grant сейчас может выбрать access preset/scopes, но не
может отдельно выбрать, разрешать ли персональные данные. В результате ChatGPT
OAuth по read-only или analytics scopes получает персональные данные, если tool
их возвращает.

## Цель

Сделать для ChatGPT OAuth явный privacy mode:

- default для новых OAuth grants: персональные данные скрыты;
- пользователь может явно разрешить персональные данные на consent screen;
- runtime OAuth access token использует тот же `RuntimeCredentials.is_depersonalized`,
  что и Bearer-токены;
- кабинет аккаунта показывает access level и personal-data mode отдельно;
- legacy grants не ломаются и получают безопасное поведение/подсказку reconnect.

## Не цели

- Не менять Vetmanager API и не добавлять новые upstream scopes.
- Не переписывать sanitizer.
- Не делать in-place переключатель privacy mode для существующего ChatGPT grant:
  изменение режима выполняется через disconnect/reconnect.
- Не менять правила access presets.

## Архитектурное решение

### Проблема

Scopes отвечают за набор разрешённых MCP tools. Privacy mode отвечает за то,
можно ли возвращать персональные поля внутри уже разрешённых tool results. Эти
оси нельзя смешивать: `Read only` может быть как без персональных данных, так и
с персональными данными, если владелец аккаунта явно согласился.

### Контекст и ограничения

- Existing pattern: Bearer path уже хранит `ServiceBearerToken.is_depersonalized`
  и tool wrapper применяет centralized sanitizer по `RuntimeCredentials`.
- OAuth runtime already resolves token -> grant -> account -> connection and
  returns `RuntimeCredentials`.
- Storage migrations должны быть backward-compatible.
- OAuth authorization code должен сохранить выбранный privacy mode, чтобы token
  exchange не зависел от формы consent после redirect.
- Секреты Vetmanager не должны попадать в UI/logs/tests.
- Public behavior меняется на более приватный default; legacy grants должны быть
  обработаны fail-safe.
- Активные OAuth access tokens, выданные до Stage 178, могут начать возвращать
  redacted данные сразу после деплоя, потому что их legacy grant marker будет
  `NULL -> depersonalized`. Это осознанный privacy-positive transition, но его
  нужно явно показать в account UI и зафиксировать в rollout notes.

### Варианты

1. Добавить новые OAuth scopes для personal-data.
   - Плюсы: privacy можно выразить в OAuth scope string.
   - Минусы: смешивает tool permissions и field-level redaction, требует новый
     scope vocabulary и сложнее объясняется пользователю.

2. Добавить отдельный `is_depersonalized` marker на OAuth grant/code.
   - Плюсы: переиспользует Bearer sanitizer, минимально меняет runtime,
     сохраняет separation of concerns.
   - Минусы: ChatGPT не видит этот режим как OAuth scope; нужно явно показывать
     режим в consent/account UI.

3. Всегда depersonalized для ChatGPT OAuth.
   - Плюсы: максимальная privacy.
   - Минусы: ломает сценарии, где владелец аккаунта осознанно хочет работать с
     клиентами по имени/телефону в ChatGPT.

Выбор: вариант 2.

### Выбранное решение

- Добавить nullable `is_depersonalized` в `oauth_authorization_codes` и
  `oauth_grants`.
- На consent screen добавить выбор:
  - `Без персональных данных` — default, сохраняет `is_depersonalized=true`;
  - `Разрешить персональные данные` — сохраняет `is_depersonalized=false`.
- Authorization code exchange копирует marker из code в grant.
- OAuth runtime resolver выставляет `RuntimeCredentials.is_depersonalized` из
  grant. `NULL` трактуется как `true` для fail-safe legacy behavior.
- Account UI показывает отдельную колонку privacy. Для legacy `NULL` показывает
  подсказку reconnect, потому что старый grant не проходил новый consent.
- Legacy active access tokens не получают grace period с персональными данными:
  `NULL` трактуется как `true` сразу. Владелец аккаунта видит guidance в
  `/account`; если ему нужны персональные данные, он отключает ChatGPT
  connection и подключает заново с явным allow.

### Инварианты

- Access preset/scopes не расширяются из-за privacy mode.
- `is_depersonalized=true` всегда приводит к existing sanitizer boundary.
- Ошибка sanitizer остаётся fail-closed.
- Legacy OAuth grants не получают новые write permissions и не раскрывают
  персональные данные по умолчанию.
- Raw OAuth/Bearer tokens не сохраняются и не показываются повторно.

### Rollback/fallback

- Миграция reversible: drop двух nullable колонок.
- Если privacy UI вызывает проблемы, можно оставить default depersonalized и
  временно скрыть опцию personal-data, не меняя storage/runtime контракт. При
  таком fallback runtime должен принудительно трактовать OAuth grants как
  depersonalized или требовать reconnect перед honoring старых
  `is_depersonalized=false` grants; нельзя просто убрать UI и оставить уже
  выданные personal-data grants раскрывающими данные.
- Если upstream ChatGPT OAuth начнёт поддерживать fine-grained data consent,
  текущий marker можно маппить из нового upstream параметра без переписывания
  sanitizer.

## Декомпозиция

### 178.1 PRD/review gates

- Создать PRD.
- Выполнить Spark-review PRD.
- Выполнить Claude Opus Architecture Critique/PRD-review.
- Зафиксировать accepted/rejected findings.

### 178.2 Storage/migration

- Добавить Alembic migration после `20260622_000016`.
- Добавить nullable `is_depersonalized` в `OAuthAuthorizationCode` и
  `OAuthGrant`.
- Обновить migration tests.

### 178.3 OAuth consent UI

- Добавить privacy mode selector на `/oauth/authorize`.
- Default: без персональных данных.
- POST `/oauth/authorize/consent` валидирует privacy mode и сохраняет в
  request data.

### 178.4 OAuth code/grant/runtime

- `create_oauth_authorization_code` сохраняет marker.
- `exchange_oauth_authorization_code` копирует marker в grant.
- `_resolve_oauth_runtime_credentials` возвращает marker в
  `RuntimeCredentials.is_depersonalized`.

### 178.5 Account UI

- `render_account` формирует privacy labels для OAuth grants.
- `render_account_page` показывает privacy отдельно от access/scopes.
- Legacy `NULL` получает reconnect guidance.

### 178.6 Tests

- Unit/migration coverage for new columns.
- OAuth consent default depersonalized and explicit personal-data allow.
- Token exchange persists grant privacy marker.
- Runtime resolver maps OAuth grant marker to credentials.
- OAuth MCP tool-call integration verifies representative personal fields are
  redacted for depersonalized ChatGPT access tokens and remain raw only after
  explicit personal-data allow.
- Legacy `is_depersonalized=NULL` grant with an already-live OAuth access token
  resolves to `RuntimeCredentials.is_depersonalized=true` and produces redacted
  tool output.
- Account UI renders privacy state.

### 178.7 Checks/review/deploy

- Full test suite.
- Audit.
- Commit.
- Spark committed diff review.
- Claude Opus committed diff review.
- Push.
- Deploy and smoke checks.
- Roadmap + AssumptionLog + work log.

## Acceptance criteria

- New ChatGPT OAuth grants are depersonalized by default.
- Explicit personal-data allow survives authorization code exchange.
- OAuth access token runtime uses existing centralized sanitizer path.
- Account owner can see both access level and personal-data mode.
- Existing/legacy grants are treated fail-safe and receive reconnect guidance.
- Unit/migration tests and full Docker test profile pass.

## PRD Review Notes

Spark-review PRD, 2026-06-23:

- Accepted: add tool-call integration coverage for OAuth sanitizer behavior.
  Resolver-only coverage would not catch wrapper/sanitizer integration
  regressions.
- Accepted: define privacy-safe fallback for existing personal-data grants if
  the UI option is temporarily disabled.

Claude Opus Architecture Critique/PRD-review, 2026-06-23:

- Accepted: document the rollout behavior for already-issued active OAuth
  tokens. Stage 178 intentionally changes legacy `NULL` grants to fail-safe
  depersonalized behavior immediately; account UI must surface reconnect
  guidance.
- Accepted: add explicit test coverage for legacy `NULL` grants with live OAuth
  access tokens, including redacted tool output.

## Completion Notes

- Implemented storage migration `20260623_000017`.
- Implemented OAuth consent privacy mode with default depersonalized behavior.
- Implemented authorization-code/grant persistence and OAuth runtime propagation
  into `RuntimeCredentials.is_depersonalized`.
- Implemented account UI privacy labels and legacy reconnect guidance.
- Added tests for migration columns, consent persistence, explicit personal-data
  allow, runtime mapping, OAuth tool-call redaction, raw explicit allow behavior,
  and legacy `NULL` live-token redaction.
- Verification: `docker compose --profile test run --rm test` — `1223 passed,
  1 skipped, 63 deselected`.
