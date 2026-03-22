# PRD: Этап 44. Security review и hardening

## Контекст

После завершения этапа 43 проект получил более жёсткий CI/test baseline и
стабильную test infrastructure. Следующий этап должен зафиксировать реальную
security-модель сервиса, прежде чем вносить hardening-изменения.

Сервис уже содержит:
- публичный web-контур (`/`, `/register`, `/login`, `/account`, `/account/*`);
- bearer-only MCP runtime;
- хранение Vetmanager credentials в encrypted storage;
- выпуск и revoke service bearer tokens;
- runtime resolution Vetmanager integration через account context;
- audit trail для token lifecycle и auth events.

Это означает, что security review должен охватить не одну точку входа, а
несколько trust boundary одновременно: browser/web, bearer runtime, storage,
upstream Vetmanager API и deployment/config layer.

## Цель этапа 44

Провести security audit bearer/web/runtime/storage контуров, зафиксировать
threat model, затем закрыть найденные риски через hardening fixes и regression tests.

## Цель 44.1

Сформировать актуальный threat model для:
- web UI;
- bearer auth;
- MCP runtime;
- storage и secret handling.

Threat model должен стать входом для подэтапов `44.2–44.6`, а не абстрактным
security-эссе.

## Решение 44.1

- Зафиксировать отдельный security artifact с:
  - активами;
  - trust boundaries;
  - основными акторами и attacker profiles;
  - entry points;
  - threat scenarios;
  - уже существующими controls;
  - приоритетными risk hypotheses для следующих задач этапа 44.
- Обязательно разделять:
  - observed controls из кода;
  - выводы/гипотезы, которые требуют следующей проверки.

## Декомпозиция 44.1

### 44.1.1 Scope capture
- Считать текущую архитектуру security-граней из `web.py`, `web_auth.py`,
  `web_security.py`, `bearer_auth.py`, `runtime_auth.py`, `storage_models.py`,
  `secret_manager.py`, `vetmanager_client.py`,
  `vetmanager_connection_service.py`.

### 44.1.2 Threat model artifact
- Создать отдельный документ threat model.
- Отразить system context, assets, actors, trust boundaries, threat list,
  current controls, open risks.

### 44.1.3 Roadmap handoff
- Явно связать risk hypotheses с подэтапами:
  - `44.2` secrets/session/cookie/CSRF/error handling
  - `44.3` authz/scope model
  - `44.4` logging/audit leakage
  - `44.5` rate limiting/abuse
  - `44.6` SSRF/host resolution/allowlist

### 44.1.4 Validation
- Обновить `Roadmap.md`, `AssumptionLog.md`.
- Прогнать обязательные проверки проекта.

## Критерии готовности 44.1

- В репозитории есть отдельный актуальный threat model artifact.
- Threat model опирается на фактическую реализацию, а не на предполагаемую.
- В документе выделены приоритетные risk hypotheses, которые напрямую
  продолжаются в `44.2–44.6`.

## Цель 44.2

Проверить контур web secrets/session/cookie/CSRF и safe error handling, чтобы
исключить слабую связку между web session secret и storage encryption key и
подтвердить, что web UI не показывает пользователю upstream/internal детали.

## Решение 44.2

- Разделить секреты по назначению:
  - web session signing должен требовать отдельный `WEB_SESSION_SECRET`;
  - `STORAGE_ENCRYPTION_KEY` остаётся только для encrypted storage.
- Зафиксировать regression test на запрет fallback
  `WEB_SESSION_SECRET <- STORAGE_ENCRYPTION_KEY`.
- Перепроверить, что текущие web ошибки остаются safe-by-default:
  - формы логина/интеграции возвращают user-safe сообщения;
  - CSRF/session cookies сохраняют `HttpOnly`/`Secure`/`SameSite` contract;
  - security headers продолжают выставляться на HTML responses.

## Декомпозиция 44.2

### 44.2.1 Secret boundary hardening
- Убрать fallback session secret на `STORAGE_ENCRYPTION_KEY`.
- Оставить явную runtime-ошибку при отсутствии `WEB_SESSION_SECRET`.

### 44.2.2 Regression coverage
- Обновить unit/web tests так, чтобы они ловили попытку неявного reuse storage key
  для web session signing.

### 44.2.3 Validation
- Прогнать целевые web auth tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.2

- Web session signing требует отдельный `WEB_SESSION_SECRET`.
- Тесты покрывают отсутствие fallback на `STORAGE_ENCRYPTION_KEY`.
- Default suite остаётся зелёным без regressions в web auth flow.

## Цель 44.3

Проверить, что bearer token scopes реально участвуют в authz, а не только
хранятся в БД как декоративный metadata field.

## Решение 44.3

- Пробросить scopes из bearer token через `BearerAuthContext` и
  `RuntimeCredentials`.
- Ввести deterministic coarse-grained scope mapping на уровне
  `VetmanagerClient`, где доступны HTTP method и request path.
- Оставить legacy fallback только для токенов без `scopes_json`:
  они продолжают получать full-access policy через существующую
  backward-compatible десериализацию.
- Зафиксировать regression test на `403`, когда токен не содержит нужного scope.

## Декомпозиция 44.3

### 44.3.1 Scope propagation
- Добавить scopes в runtime auth context.

### 44.3.2 Request-level enforcement
- Ввести mapping `method + entity path -> required scope`.
- Проверять его до outbound HTTP request.

### 44.3.3 Regression coverage
- Добавить тесты на:
  - наличие scopes в resolved runtime context;
  - отказ для запроса вне разрешённого scope.

### 44.3.4 Validation
- Прогнать целевые bearer/runtime tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.3

- Scope model влияет на runtime authz, а не только на storage.
- Токен без нужного scope получает локальный `403` до upstream call.
- Legacy токены без `scopes_json` сохраняют full-access compatibility.

## Цель 44.4

Проверить audit/logging контур на утечки секретов и sensitive metadata и
добавить защиту на уровне общего audit-layer, а не только отдельных callsite'ов.

## Решение 44.4

- Ввести defensive sanitization в `auth_audit` перед сериализацией `details`.
- Скрывать или редактировать поля с типовыми sensitive ключами:
  raw token, `api_key`, `user_token`, `password`, `authorization`, cookie/session.
- Сохранить полезные non-secret audit fields (`token_prefix`, `account_id`,
  `connection_id`, `domain`, event metadata).
- Зафиксировать regression tests, что audit log не сохраняет raw secret material,
  даже если такой payload случайно передан в helper.

## Декомпозиция 44.4

### 44.4.1 Sensitive-field policy
- Зафиксировать список ключей/паттернов, которые подлежат redaction.

### 44.4.2 Audit-layer hardening
- Добавить sanitization в `_serialize_details()` или рядом с ним.

### 44.4.3 Regression coverage
- Добавить unit tests на redaction.
- Подтвердить, что существующие bearer/web audit flows остаются зелёными.

### 44.4.4 Validation
- Прогнать целевые audit/bearer/web tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.4

- Audit trail не сохраняет raw secret material даже при ошибке callsite'а.
- Полезные operational metadata сохраняются.
- Regression tests покрывают redaction policy.

## Цель 44.5

Проверить rate limiting и abuse surface вокруг web/bearer auth, в первую очередь
убрав прямое доверие к spoofable forwarded headers.

## Решение 44.5

- Ввести explicit trusted-proxy policy для определения client IP.
- Использовать одну и ту же policy для web rate limiting и audit metadata.
- Игнорировать `X-Forwarded-For`, если immediate client host не входит в
  allowlist trusted proxies.
- Зафиксировать regression tests на spoofing-resistant поведение.

## Декомпозиция 44.5

### 44.5.1 Trusted proxy contract
- Определить env-driven allowlist trusted proxy IP/host values.

### 44.5.2 Shared client IP resolution
- Вынести/переиспользовать helper для web rate limiting и auth audit.

### 44.5.3 Regression coverage
- Добавить тесты на:
  - игнорирование spoofed `X-Forwarded-For` без trusted proxy;
  - учёт forwarded chain только за trusted proxy.

### 44.5.4 Validation
- Прогнать целевые web/audit tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.5

- Spoofed `X-Forwarded-For` больше не влияет на limiter и audit по умолчанию.
- Reverse proxy deployment может явно включить доверие через allowlist.
- Web и audit используют одинаковую политику client IP resolution.

## Цель 44.6

Проверить SSRF/host resolution/allowlist контур и исключить обходы через
userinfo, custom ports и небезопасные non-origin billing responses.

## Решение 44.6

- Вынести общий validator resolved origin для runtime client и account
  integration service.
- Разрешать только bare HTTPS origin:
  - без userinfo;
  - без custom port;
  - без path/query/fragment;
  - только с allowlisted suffix.
- Нормализовать валидный host к canonical origin.
- Добавить regression tests на path/query, userinfo и custom-port bypass.

## Декомпозиция 44.6

### 44.6.1 Shared host validator
- Вынести общую функцию в отдельный модуль.

### 44.6.2 Runtime + account integration hardening
- Подключить общий validator в `VetmanagerClient` и
  `vetmanager_connection_service`.

### 44.6.3 Regression coverage
- Добавить тесты на reject userinfo/custom port/path/query billing host.

### 44.6.4 Validation
- Прогнать целевые client/connection-service tests.
- Прогнать обязательный default contour.

## Критерии готовности 44.6

- Billing-resolved host должен быть bare HTTPS origin.
- Client и account integration используют одинаковую allowlist policy.
- Regression tests закрывают типовые SSRF/bypass формы.

## Цель 44.7

Собрать результаты `44.2–44.6` в явный hardening outcome и подтвердить, что
отдельного незакрытого security fix bucket после аудита не осталось.

## Решение 44.7

- Зафиксировать, что найденные medium/high-priority fixes были реализованы
  инкрементально в подпунктах:
  - `44.2` secret boundary;
  - `44.3` scope enforcement;
  - `44.4` audit redaction;
  - `44.5` trusted proxy policy;
  - `44.6` bare-origin host validation.
- Не добавлять искусственный “ещё один fix commit”, если реальные изменения уже
  внесены и проверены в предыдущих задачах.

## Критерии готовности 44.7

- В roadmap и артефактах явно сказано, где именно были реализованы hardening fixes.
- После `44.6` не остаётся незакрытого технического хвоста по findings этапа 44,
  кроме документации и финальной упаковки regressions.

## Цель 44.8

Собрать ключевые security regressions в явный pytest subset, чтобы их можно было
запускать и сопровождать как отдельный security baseline.

## Решение 44.8

- Ввести marker `security`.
- Пометить критичные regression tests по:
  - session secret boundary;
  - scope enforcement;
  - safe auth errors;
  - audit redaction;
  - trusted proxy policy;
  - bare-origin host validation.

## Критерии готовности 44.8

- В `pytest.ini` зарегистрирован marker `security`.
- Ключевые security-invariant tests помечены этим marker'ом.
- `pytest -m security` проходит зелёным.
