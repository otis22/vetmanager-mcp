# Security Threat Model: vetmanager-mcp

Дата фиксации: 2026-03-22

## 1. Scope

Модель покрывает четыре security-контура:
- public web UI;
- bearer auth и service token lifecycle;
- MCP runtime и outbound Vetmanager access;
- storage и secret handling.

## 2. System Context

Высокоуровневая схема:
- браузер пользователя работает с публичным web UI;
- web UI создаёт service account, сохраняет Vetmanager integration и выпускает
  service bearer tokens;
- MCP-клиент вызывает tools/prompts только с `Authorization: Bearer <service_token>`;
- runtime по bearer token резолвит account + active Vetmanager connection;
- Vetmanager credentials хранятся только в encrypted storage;
- для `login/password -> user token` пароль используется только для exchange,
  а затем хранится только выданный user token;
- runtime и web обращаются к billing API и Vetmanager upstream over HTTPS.

## 3. Assets

Критичные активы:
- raw service bearer token во время one-time issuance;
- действующий Vetmanager API key или user token;
- `STORAGE_ENCRYPTION_KEY`;
- `WEB_SESSION_SECRET`;
- signed web session cookie;
- CSRF token pair (cookie + hidden field);
- encrypted credentials в `vetmanager_connections.encrypted_credentials`;
- token hash/prefix и lifecycle metadata в `service_bearer_tokens`;
- audit/usage logs и request metadata.

Средней критичности:
- account email/password hash;
- integration health status;
- token usage counters;
- resolved Vetmanager host.

Низкой критичности:
- landing content;
- generic tool metadata/schema.

## 4. Trust Boundaries

### Boundary A: Internet -> Public Web UI

Недоверенная граница.

Входы:
- `GET /`
- `GET/POST /register`
- `GET/POST /login`
- `POST /logout`
- `GET /account`
- `POST /account/integration`
- `POST /account/integration/reauth`
- `POST /account/tokens`
- `POST /account/tokens/{id}/revoke`

### Boundary B: MCP Client -> Runtime

Недоверенная граница.

Вход:
- `Authorization: Bearer <service_token>`
- business params tool/prompt calls

### Boundary C: App -> Storage

Полудоверенная граница.

Риски:
- компрометация DB dump;
- misuse дешифрования при компрометации env secrets;
- накопление sensitive metadata в audit tables.

### Boundary D: App -> External Upstream

Внешняя недоверенная граница:
- `billing-api.vetmanager.cloud`
- resolved clinic host under allowlisted suffix
- `/token_auth.php`
- `/rest/api/*`

### Boundary E: Deployment / Reverse Proxy / Headers

Условно доверенная граница.

Риски:
- spoofed forwarding headers;
- неверные cookie/HTTPS defaults behind proxy;
- leakage через logs/ops tooling.

## 5. Actors

### Legitimate Actors

- анонимный посетитель landing/register/login;
- аутентифицированный владелец service account;
- MCP client, использующий service bearer token;
- Vetmanager upstream.

### Threat Actors

- внешний анонимный атакующий без учётной записи;
- атакующий с украденным bearer token;
- атакующий с украденной web session cookie;
- вредоносный или скомпрометированный proxy/reverse proxy;
- оператор с доступом к DB dump или application logs;
- скомпрометированный upstream host или ложный host resolution response.

## 6. Entry Points

Основные входы:
- browser forms и session cookies;
- MCP Authorization header;
- env/config secrets;
- database rows with encrypted secrets and token metadata;
- outbound HTTP to billing API and clinic upstream;
- audit/usage logging path.

## 7. Current Security Controls Observed In Code

Наблюдаемые controls:
- bearer-only runtime через `request_auth.get_bearer_token()`;
- runtime не принимает `X-VM-Domain` / `X-VM-Api-Key`;
- service bearer token хранится hash-only, raw token не сохраняется;
- Vetmanager credentials хранятся только в encrypted payload;
- `login/password` не сохраняются, используются только для token exchange;
- resolved host валидируется на `https` и allowlisted suffix;
- web session cookie подписана HMAC и `httponly=True`;
- cookie defaults: `secure=True` и `samesite=strict`, если явно не ослаблены env;
- signed CSRF double-submit token;
- shared rate limiting для `/register`, `/login`, bearer auth: in-memory by
  default, Redis-backed при `REDIS_URL`;
- one-time display raw bearer token after issuance;
- audit trail для token lifecycle и auth events;
- safe error detail extraction для user-token exchange, без возврата raw upstream body;
- integration health умеет переводить stored user token в `reauth_required`.

## 8. Threat Scenarios

### T1. Theft or replay of service bearer token

Последствие:
- полный доступ к MCP runtime в рамках scopes/connection account.

Текущие controls:
- hash-only storage;
- revoke/expiry;
- request counters и audit logs;
- bearer rate limiting.

Открытые вопросы:
- достаточно ли scope model ограничивает blast radius;
- есть ли gaps around token rotation and least privilege.

### T2. Theft or replay of web session cookie

Последствие:
- захват account UI, выпуск новых bearer tokens, замена Vetmanager integration.

Текущие controls:
- signed cookie;
- `httponly`;
- CSRF layer;
- secure/samesite defaults.

Открытые вопросы:
- нет server-side session store или session revocation list;
- fallback `WEB_SESSION_SECRET <- STORAGE_ENCRYPTION_KEY` связывает два trust domain.

### T3. CSRF against state-changing web routes

Последствие:
- silent integration overwrite или token issuance/revoke.

Текущие controls:
- signed CSRF cookie + signed submitted token;
- validation on state-changing routes.

Открытые вопросы:
- нужно проверить покрытие всех state-changing endpoints и safe error paths.

### T4. Brute force / abuse on register, login, bearer auth

Последствие:
- credential stuffing;
- noisy token replay;
- service degradation.

Текущие controls:
- shared rate limiting с Redis-backed режимом для multi-worker deploy.

Открытые вопросы:
- без `REDIS_URL` limiter state process-local и не shared between instances;
- Redis backend fail-open по умолчанию деградирует в process-local fallback;
  для fail-closed enforcement нужен `RATE_LIMIT_REQUIRE_REDIS=1`;
- доверие к `X-Forwarded-For` может ослабить IP-based protection.

### T5. Secret disclosure via logs, errors, HTML, audit trail

Последствие:
- утечка API key, user token, passwords, raw bearer token.

Текущие controls:
- raw bearer token one-time only;
- HTML account page не показывает stored secret values повторно;
- login/password flow не хранит пароль;
- audit details intended to contain safe metadata only.

Открытые вопросы:
- нужен целевой audit logging review на leakage в details_json, exceptions,
  user-facing errors и debug logs.

### T6. SSRF / host spoofing via billing resolution

Последствие:
- outbound requests на attacker-controlled host;
- credential exfiltration.

Текущие controls:
- domain format validation;
- HTTPS-only;
- allowlisted host suffixes.

Открытые вопросы:
- нужно отдельно проверить все paths host resolution и reuse resolved host;
- нужно проверить, нет ли обходов через unusual hostnames / redirects / ports.

### T7. Database dump compromise

Последствие:
- attacker получает encrypted credentials, password hashes, token metadata,
  usage logs.

Текущие controls:
- encrypted Vetmanager credentials;
- hash-only bearer token storage;
- password hashing with PBKDF2-HMAC-SHA256 + per-password salt.

Открытые вопросы:
- компрометация `STORAGE_ENCRYPTION_KEY` полностью меняет risk picture;
- нужна policy по key rotation / separation of duties.

### T8. Overbroad authorization via bearer -> account connection resolution

Последствие:
- токен может получить больше MCP capabilities, чем должен.

Текущие controls:
- token status/expiry/revoke checks;
- active account + active connection requirement;
- scope manifest exists in token model.

Открытые вопросы:
- нужно проверить, реально ли scopes применяются на runtime/tool layer;
- нужно проверить legacy full-access fallback.

### T9. Proxy/header spoofing and metadata trust

Последствие:
- ложный IP в limiter/audit;
- искажение расследования инцидентов;
- обход abuse controls.

Текущие controls:
- best-effort metadata capture.

Открытые вопросы:
- код напрямую доверяет `X-Forwarded-For`, если он присутствует;
- нет documented trusted-proxy policy.

## 9. Highest-Priority Risk Hypotheses For Next Tasks

### For 44.2

- coupling `WEB_SESSION_SECRET` with `STORAGE_ENCRYPTION_KEY` ослабляет
  разделение secret domains;
- нужно проверить cookie/session defaults и safe error handling на всех web paths;
- нужно проверить, нет ли user-facing error leaks от upstream.

### For 44.3

- scope model может быть шире, чем фактический least-privilege contract;
- legacy fallback to full access требует отдельной оценки.

### For 44.4

- audit trail и error surface могут содержать sensitive metadata, хотя секреты
  явно не должны попадать в logs.

### For 44.5

- in-memory rate limiting без `REDIS_URL` может быть недостаточен для
  multi-instance deploy;
- direct trust to `X-Forwarded-For` может делать limiter и audit spoofable.

### For 44.6

- allowlist есть, но нужен отдельный review на SSRF/host validation completeness,
  включая redirects, нестандартные host representations и reuse resolved host.

## 9.7 Remediation Status (обновлено 2026-03-27)

| Гипотеза | Статус | Этапы | Примечание |
|----------|--------|-------|------------|
| 44.2 (secrets coupling, cookie defaults) | Частично закрыто | 44, 52 | Session timeout 24h, CSP headers, fail-fast startup validation. WEB_SESSION_SECRET / STORAGE_ENCRYPTION_KEY coupling остаётся by design. |
| 44.3 (scope model) | Подготовлено | 28 | Schema/storage готовы, enforcement не включён. Legacy tokens → full access. |
| 44.4 (audit log leaks) | Закрыто | 44, 52 | Upstream error text stripped, JSON CSP, safe error messages. |
| 44.5 (rate limiting, XFF) | Частично закрыто | 27, 40, 52, 138 | Per-token, per-email lockout, per-IP limiting реализованы. Web/bearer rate limiting используют shared backend: in-memory default, Redis-backed при `REDIS_URL`; без Redis остаётся process-local limitation. `WEB_TRUSTED_PROXY_IPS` добавлен (stage 52). |
| 44.6 (SSRF/host validation) | Закрыто | 12, 44 | Domain validation + HTTPS + allowlist суффиксов. Redirect following disabled. |

## 10. Security Review Output Contract

Что считать успешным продолжением threat model на следующих шагах:
- каждый риск из `44.2–44.6` должен ссылаться на один или несколько сценариев
  из этого документа;
- hardening fixes `44.7` должны быть traceable обратно к конкретным threat'ам;
- regression tests `44.8` должны проверять именно security-invariant, а не
  общую happy-path функциональность.
