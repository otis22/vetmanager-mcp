# vetmanager-mcp

[![Tests](https://github.com/otis22/vetmanager-mcp/actions/workflows/test.yml/badge.svg)](https://github.com/otis22/vetmanager-mcp/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **English speakers:** This project is documented in Russian. The API and MCP protocol are language-agnostic and work with any MCP-compatible client. Google Translate handles technical documentation well. See [Quick Start](#быстрый-старт-локально) to get running in 3 commands.

MCP-сервер для интеграции [Vetmanager REST API](https://help.vetmanager.cloud/article/3029) с любым клиентом, поддерживающим [Model Context Protocol](https://modelcontextprotocol.io/). Позволяет управлять операциями ветеринарной клиники через диалоговых AI-агентов на естественном языке.

Сервер берёт на себя bearer-аутентификацию сервиса, хранение Vetmanager credentials на уровне service account, динамическое определение URL API (через `billing-api.vetmanager.cloud`) и форматирование данных. Runtime-контур теперь **bearer-only**: MCP-клиент передаёт только `Authorization: Bearer <service_token>`, а активное Vetmanager-подключение определяется через account context.

Privacy / auth boundary:
- сервис не сохраняет бизнес-данные Vetmanager для постоянного хранения;
- сервис хранит только технические данные integration и metadata сервисных bearer-токенов;
- для режима `login/password -> user token` логин и пароль используются только для token exchange и не сохраняются в storage;
- при смене пароля в Vetmanager сохранённый user token может стать невалидным, и тогда в кабинете потребуется повторная авторизация.

## Требования

- Docker (с плагином Compose)
- `ssh-copy-id` настроен для деплоя на удалённый сервер
- Python на хосте **не требуется** — всё работает через Docker

## Быстрый старт (локально)

```bash
cp .env.example .env          # задайте UID/GID и LOG_LEVEL
docker compose build
docker compose up -d          # запустить MCP-сервер
```

После запуска:

- публичный лендинг доступен на `http://localhost:8000/`
- MCP endpoint остаётся на `http://localhost:8000/mcp`

Полезные runtime-переменные:

- `DATABASE_URL` — строка подключения к БД. По умолчанию используется локальный `sqlite+aiosqlite:///./data/vetmanager.db`.
- `STORAGE_ENCRYPTION_KEY` — ключ шифрования для сохранённых Vetmanager secrets. В production должен быть задан явно.
- `WEB_SESSION_SECRET` — секрет подписи web session cookie для `/register`, `/login`, `/account`. В production должен быть задан явно.
- `WEB_SESSION_MAX_AGE_SECONDS` — срок жизни web session cookie. По умолчанию 86 400 (24 часа).
- `WEB_TRUSTED_PROXY_IPS` — список доверенных reverse proxy IP/host через запятую; только для них сервис учитывает `X-Forwarded-For`.
- `SITE_BASE_URL` — базовый URL self-hosted инсталляции (используется в canonical/og:url лендинга и в mcp.json snippet на странице аккаунта). По умолчанию `https://vetmanager-mcp.vromanichev.ru` (prod). Для self-hosted — задайте свой домен (без trailing slash).
- `ERROR_TRACKING_DSN` / `SENTRY_DSN` — opt-in DSN для отправки unhandled errors в Sentry.
- `ERROR_TRACKING_ENVIRONMENT`, `ERROR_TRACKING_RELEASE`, `ERROR_TRACKING_TRACES_SAMPLE_RATE` — knobs для error tracking bootstrap.
- `PORT`, `MCP_PATH`, `LOG_LEVEL` — стандартные настройки MCP HTTP runtime.

Operational helpers:
- `scripts/post_deploy_smoke_checks.sh` — post-deploy checks для `/healthz`,
  `/readyz`, `/metrics` и `/mcp`.
  Поддерживает retry/grace knobs через env:
  `SMOKE_MAX_ATTEMPTS`, `SMOKE_SLEEP_SECONDS`,
  `SMOKE_CONNECT_TIMEOUT_SECONDS`, `SMOKE_CURL_MAX_TIME_SECONDS`.
  При падении deploy script дополнительно печатает `docker compose ps` и tail
  container logs для fast triage.
  Deploy path также принудительно выравнивает `UID`/`GID` для `docker compose`
  и заранее создаёт локальный `data/`, чтобы SQLite storage мог стартовать на
  bind-mounted репозитории без permission drift.

Запуск тестов:

```bash
# default contour: unit + mock + live browser happy-path tests
# Chromium уже предустановлен в test image, доп. setup не нужен
docker compose --profile test run --rm test

# fast contour: без browser и real contour tests
docker compose --profile test run --rm test sh -c "python scripts/run_fast_test_suite.py"

# security contour: только security regressions этапа 44
docker compose --profile test run --rm test sh -c "python -m pytest -m security -q"

# opt-in real contour: real API и real browser tests
docker compose run --rm \
  -e TEST_DOMAIN=<домен> \
  -e TEST_API_KEY=<ключ> \
  test sh -c "python scripts/run_opt_in_real_test_suite.py"

# opt-in real contour с direct real smoke для уже выданного user-token
docker compose run --rm \
  -e TEST_DOMAIN=<домен> \
  -e TEST_USER_TOKEN=<user_token> \
  test sh -c "python scripts/run_opt_in_real_test_suite.py"

# opt-in real contour с login/password -> user token exchange
docker compose run --rm \
  -e TEST_DOMAIN=<домен> \
  -e TEST_USER_TOKEN_BASE_URL=<https://clinic.vetmanager2.ru> \
  -e TEST_USER_LOGIN=<login> \
  -e TEST_USER_PASSWORD=<password> \
  test sh -c "python scripts/run_opt_in_real_test_suite.py"
```

Тестовые контуры:
- `fast`:
  быстрый inner-loop без Playwright/browser и без real API/browser tests.
- `default`:
  unit + mock/e2e + live localhost browser tests, без реального Vetmanager API.
- `opt_in_real`:
  real API e2e + real browser tests; real browser flow дополнительно требует
  `RUN_REAL_BROWSER_TESTS=1`.

Safe workflow для real/browser verification:
- использовать только env-driven `TEST_*` и `RUN_REAL_BROWSER_TESTS=1`, не
  записывать clinic credentials в репозиторий;
- для `login/password -> user token` real flow сервис повторяет production
  контракт Vetmanager:
  `POST /token_auth.php` c `app_name=vetmanager-mcp`, затем
  `X-USER-TOKEN` + `X-APP-NAME` на последующих API-запросах;
- для production browser checks использовать временный account и удалять его
  после ручной верификации, чтобы не копить тестовые сущности в production.

Что входит в default `docker compose --profile test run --rm test`:
- unit tests;
- mock/e2e tests;
- live localhost browser tests через Playwright;
- browser happy-path tests для обоих web auth flows;
- cleanup regression для browser-created account data;
- zero-warning quality gate через warning-as-error launcher.

## Observability

HTTP probes и scrape endpoints:
- `GET /healthz` — process liveness, не ходит во внешние зависимости.
- `GET /readyz` — readiness probe; сейчас проверяет storage через `SELECT 1`.
- `GET /metrics` — Prometheus-compatible text exposition для process-local service metrics.

Что собирается из коробки:
- structured logs c `request_id`, `correlation_id`, `event_category`, `event_name`;
- `runtime` / `audit` / `security` logger taxonomy;
- service metrics:
  - `vetmanager_http_requests_total` + `vetmanager_http_request_latency_seconds_{count,sum,max}` — inbound HTTP web routes;
  - `vetmanager_auth_failures_total{source,reason}` — bearer/web auth failures grouped by reason;
  - `vetmanager_upstream_failures_total{target,reason}` — failures to VM/billing upstream (timeout / network_error / http_5xx / circuit_open);
  - `vetmanager_upstream_requests_total{target,status}` + `vetmanager_upstream_request_latency_seconds_{count,sum,max}` — all VM API requests with their outcome (stage 88);
  - `vetmanager_tool_calls_total{endpoint,method,outcome}` + `vetmanager_tool_call_latency_seconds_{count,sum,max}` — per-tool (endpoint+method) latency and success/error rate via crud_helpers instrumentation (stage 88);
  - `vetmanager_cache_{hits,misses,invalidations,evictions}_total` + `vetmanager_cache_entries`;
  - `vetmanager_business_events_total{event=...}` — lifecycle business events (`account_registered`, `web_login_succeeded`, `bearer_token_issued`, `bearer_token_revoked`) (stage 110);
  - `vetmanager_token_preset_issued_total{preset}` — issuance counter by access preset;
  - `vetmanager_rate_limit_backend_degraded_total{reason}` — Redis rate-limit backend fallback/strict failure counter;
  - `vetmanager_sanitizer_failures_total` — depersonalized response sanitizer failures;
  - `/metrics` endpoint gated by optional `METRICS_AUTH_TOKEN` env (stage 111.1): when set, requires `Authorization: Bearer <token>` or returns 403;
  - invalid `/metrics` bearer attempts increment `vetmanager_auth_failures_total{source="metrics",reason="invalid_token"}` and emit a `security` log event `metrics_auth_failed`;
- opt-in Sentry bootstrap для unhandled exceptions.

### Exceptions raised by VM tools

Все клиенты MCP tools ловят исключения наследники `VetmanagerError`:
- `AuthError` — 401/403 от Vetmanager (неверный токен/доступ запрещён);
- `NotFoundError` — 404 (ресурс не существует);
- `VetmanagerTimeoutError` — истёк timeout upstream запроса;
- `VetmanagerUpstreamUnavailable` (stage 91) — circuit breaker OPEN для domain, fast-fail без вызова upstream. Наследует `VetmanagerError`, поэтому existing `except VetmanagerError:` ловят его без изменений;
- `RateLimitError` — срабатывание локального rate limiter'а;
- `HostResolutionError` — сбой резолва VM-хоста через billing API;
- `VetmanagerError` — база для upstream 5xx и протокольных ошибок.

Error tracking:
- без `ERROR_TRACKING_DSN`/`SENTRY_DSN` integration не активируется;
- pattern-based sanitizer (stage 89) редактирует заголовки/cookies/query/body по substring'ам `token|key|secret|auth|api|cookie|bearer|password|credential|session|csrf|signature|jwt|hmac|otp|passphrase`, с whitelist для observability headers (`x-request-id`, `x-correlation-id`, `x-api-version` и т.д.).

Отдельный runbook по эксплуатации observability-контура:
- `artifacts/observability-runbook-vetmanager-mcp-ru.md`

## Bearer-only runtime

Рабочий MCP runtime больше не принимает `X-VM-Domain` и `X-VM-Api-Key` в HTTP-заголовках. Все tools и prompts работают только через `Authorization: Bearer <service_token>`.

Bearer-токен привязан к account сервиса:

- `service_bearer_token` идентифицирует account;
- account хранит ровно одно активное `vetmanager_connection`;
- активное connection поддерживает auth mode `domain + rest_api_key` и `login/password -> user token`;
- домен и Vetmanager API key хранятся в storage-слое и не передаются в MCP tool arguments.

### Текущий статус provisioning

Пользовательский web-контур уже начал работать:

- лендинг перепозиционирован под ветврачей, администраторов и руководителей клиник;
- регистрация вынесена в главный CTA главной страницы;
- доступны лендинг, регистрация account и login/logout;
- доступна страница `/account`;
- доступна настройка активной Vetmanager integration через wizard:
  сначала выбор способа авторизации, затем только релевантные поля;
- доступна настройка `domain + rest_api_key`;
- доступна настройка user-token integration через `domain + login/password -> user token`;
- логин и пароль Vetmanager не сохраняются и не отображаются повторно после submit;
- для token exchange используется `POST /token_auth.php` с `multipart/form-data`
  и фиксированным `app_name=vetmanager-mcp`, без `X-REST-API-KEY`;
- для нового account кабинет показывает onboarding state с явным следующим шагом;
- state-changing web forms защищены signed CSRF token layer;
- `/register`, `/login` и bearer runtime защищены shared rate limiting:
  in-memory по умолчанию, Redis-backed при `REDIS_URL`;
- HTML responses отдают baseline security headers: `CSP`, `X-Frame-Options`, `Referrer-Policy`, `X-Content-Type-Options`;
- кабинет показывает health активной integration и статус `reauth_required`, если сохранённый user token больше не проходит валидацию;
- доступен выпуск Bearer-токенов с именем, сроком действия, preset'ом доступа
  (`full_access`, `read_only`, `frontdesk`, `doctor`, `finance`, `inventory`)
  и опциональным режимом деперсонализации ответов;
- web-выпуск безопасен по умолчанию: blank expiry становится 30 days,
  default preset — `read_only`, а `full_access` и `*.*.*.*` IP mask требуют
  явного подтверждения в форме;
- после выпуска raw bearer token показывается в отдельной success-card в верхней части страницы и может быть скопирован кнопкой;
- доступен список токенов со статусом, сроком действия, `last_used_at`, `request_count` и revoke action.

На текущем этапе в репозитории уже есть:

- storage foundation и миграции для `accounts`, `vetmanager_connections`, `service_bearer_tokens`;
- шифрование Vetmanager credentials;
- hash-only хранение bearer-токенов;
- сервис сохранения Vetmanager connection `domain + rest_api_key`;
- web exchange `login/password -> user token` c сохранением только полученного user token;
- web auth для account через email/password и signed cookie session;
- account onboarding wizard с выбором `API key` или `login/password`;
- signed CSRF layer для `/register`, `/login`, `/logout` и `/account/*`;
- rate limiting для `/register`, `/login` и bearer runtime через общий backend;
- baseline security headers для HTML-ответов web UI;
- web-экран сохранения active Vetmanager integration;
- web-выпуск Bearer-токенов с preset-based scopes и one-time показом raw значения;
- централизованная деперсонализация ответов для токенов с включённым флагом:
  structured PII поля маскируются, free-text scrub ограничен whitelist clinical
  fields, а при ошибке sanitizer'а raw payload не возвращается;
- success-card для нового raw bearer token с copy action;
- список Bearer-токенов с usage metadata;
- runtime usage accounting (`last_used_at`, `request_count`);
- безопасный audit log для create/revoke Bearer-токенов.

То есть runtime-контракт уже bearer-only, а account provisioning, Vetmanager integration, token management, security baseline web-контура и продуктовый landing больше не internal-only.

## Подключение Cursor

### Шаг 1 — запустить сервер

```bash
cp .env.example .env          # задайте UID/GID и LOG_LEVEL при необходимости
docker compose up -d mcp
```

### Шаг 1.1 — создать web account

- `http://localhost:8000/register` — регистрация account
- `http://localhost:8000/login` — вход в account
- `http://localhost:8000/account` — кабинет после входа, включая Vetmanager integration, выпуск Bearer-токенов и их список

### Шаг 2 — настроить `~/.cursor/mcp.json`

```json
{
  "mcpServers": {
    "vetmanager": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer vm_st_your_service_token"
      }
    }
  }
}
```

- `Authorization` должен содержать service bearer token, выданный для account сервиса.
- `domain` и `api_key` больше не указываются в `mcp.json` и не передаются в tool arguments.

### Политика credentials

| Контекст | Где берутся credentials |
|----------|------------------------|
| Cursor / Claude | `~/.cursor/mcp.json` → `Authorization: Bearer <service_token>` |
| Vetmanager `domain` / `api_key` | активное `vetmanager_connection` выбранного account |
| Явный аргумент инструмента | не поддерживается |
| e2e real tests (api_key) | `TEST_DOMAIN` / `TEST_API_KEY` в `.env` или CI secrets |
| e2e real tests (user_token) | `TEST_USER_TOKEN` или `TEST_USER_TOKEN_BASE_URL` + `TEST_USER_LOGIN` + `TEST_USER_PASSWORD` |
| Проектный `.env` (runtime) | используется только для infra-конфига (`DATABASE_URL`, `STORAGE_ENCRYPTION_KEY`, transport settings) |

### Production notes

- Rate limiting по умолчанию in-memory и process-local. Для multi-worker /
  multi-instance production задайте `REDIS_URL`, чтобы web и bearer limit state
  использовали общий backend.
- Redis backend задаёт bounded connect/socket/operation timeouts. При временной
  недоступности Redis default policy fail-open деградирует в process-local
  fallback и увеличивает `vetmanager_rate_limit_backend_degraded_total{reason}`;
  `RATE_LIMIT_REQUIRE_REDIS=1` делает init/runtime failures fail-closed.
- Текущий CSRF/session hardening рассчитан на single-instance deployment с
  общим `WEB_SESSION_SECRET`; при горизонтальном масштабировании нужен единый
  secret и согласованный deployment policy.
- Для production рекомендуется:
  - явный `WEB_SESSION_SECRET`;
  - явный `STORAGE_ENCRYPTION_KEY`;
  - раздельное хранение этих двух секретов;
  - `WEB_TRUSTED_PROXY_IPS=<ip1,ip2>` только если сервис реально стоит за
    доверенным reverse proxy;
  - `WEB_ENABLE_HSTS=1` за HTTPS reverse proxy;
  - внешний rate limit на `/register` и `/login`.
- Для error tracking в production:
  - задавать только production DSN;
  - держать `ERROR_TRACKING_TRACES_SAMPLE_RATE=0` или низкое значение, если
    нужен только exception tracking;
  - проверять, что reverse proxy не добавляет в headers чувствительные данные,
    которые не нужны приложению.
- Billing-resolved Vetmanager host теперь принимается только как bare HTTPS
  origin: без `userinfo`, custom port и path/query/fragment.
- Отдельные deployment notes по security baseline этапа 44:
  `artifacts/security-deployment-notes-vetmanager-mcp-ru.md`.
- Observability runbook этапа 45:
  `artifacts/observability-runbook-vetmanager-mcp-ru.md`.
- Operations readiness baseline этапа 47:
  `artifacts/operations-readiness-vetmanager-mcp-ru.md`.
- Release checklist этапа 47:
  `artifacts/release-checklist-vetmanager-mcp-ru.md`.

### Тест подключения

После запуска сервера и настройки `mcp.json` в чате Cursor попросите:

> «Покажи список клиентов клиники» — инструмент `get_clients` вызовется с bearer-derived account context.

## Деплой на сервер

Предусловие: `ssh-copy-id user@host` выполнен.

Прод-хост проекта: `<your-domain>` (например, `mcp.example.com`).

```bash
# Первичная настройка (один раз)
./scripts/init_server.sh user@host

# Обновление кода и перезапуск
./scripts/deploy_server.sh user@host
```

По умолчанию код размещается в `/opt/vetmanager-mcp`. Альтернативный путь:

```bash
./scripts/init_server.sh user@host /srv/vetmanager-mcp
./scripts/deploy_server.sh user@host /srv/vetmanager-mcp
```

### Режим для приватного репозитория: rsync + deploy

Если сервер не может делать `git clone/pull` (приватный repo), используйте синхронизацию кода по SSH:

```bash
./scripts/sync_and_deploy_server.sh root@<your-server-ip> /opt/vetmanager-mcp
```

Скрипт:
- синхронизирует проект через `rsync` (без `.git`, `.env`, служебных директорий);
- запускает `deploy_server.sh` с `SKIP_GIT_PULL=1`;
- выполняет те же smoke-check и TLS-check, что обычный deploy.

### Post-deploy smoke

Локально или на сервере можно прогнать:

```bash
./scripts/post_deploy_smoke_checks.sh
./scripts/post_deploy_smoke_checks.sh http://127.0.0.1:8000 <your-domain>
```

Если `/metrics` защищён `METRICS_AUTH_TOKEN`, smoke script автоматически
передаёт `Authorization: Bearer $METRICS_AUTH_TOKEN`.

### Полностью автоматический деплой после push в main

Добавлен workflow: `.github/workflows/deploy-prod.yml`.

Он срабатывает после успешного workflow `Tests` для ветки `main` и делает:
- `rsync` кода на прод-сервер;
- запуск `deploy_server.sh` в режиме `SKIP_GIT_PULL=1`.

Нужные GitHub Secrets:
- `PROD_SSH_TARGET` (пример: `root@<your-server-ip>`)
- `PROD_SSH_PRIVATE_KEY` (приватный ключ для SSH)
- `PROD_REMOTE_DIR` (опционально, по умолчанию `/opt/vetmanager-mcp`)
- `PROD_SSL_DOMAIN` (опционально, ваш домен)
- `PROD_CERTBOT_EMAIL` (опционально, email для certbot)

### TLS (Let's Encrypt) и автообновление

`init_server.sh` настраивает `nginx` reverse proxy, а `deploy_server.sh` автоматически вызывает проверку сертификата:
- если сертификата нет — будет первичный выпуск;
- если до истечения осталось меньше 30 дней — будет выполнено продление;
- после обновления сертификата `nginx` перезагружается автоматически.

При необходимости можно переопределить домен и email для certbot:

```bash
SSL_DOMAIN=mcp.example.com CERTBOT_EMAIL=ops@example.com \
./scripts/init_server.sh root@<your-server-ip>

SSL_DOMAIN=mcp.example.com CERTBOT_EMAIL=ops@example.com \
./scripts/deploy_server.sh root@<your-server-ip>
```

Обязательные внешние условия:
- DNS A-record вашего домена должен указывать на IP сервера;
- на сервере/в облачном firewall должны быть открыты порты `80/tcp` и `443/tcp`.

### Прод-конфиг Cursor MCP (локально, не в репозиторий)

Добавьте отдельный сервер в локальный `~/.cursor/mcp.json`.

**Только прод:**

```json
{
  "mcpServers": {
    "vetmanager-prod": {
      "url": "https://<your-domain>/mcp",
      "headers": {
        "Authorization": "Bearer vm_st_prod_service_token"
      }
    }
  }
}
```

**Оба сервера (локальный + прод) одновременно:**

```json
{
  "mcpServers": {
    "vetmanager-local": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "Authorization": "Bearer vm_st_local_service_token"
      }
    },
    "vetmanager-prod": {
      "url": "https://<your-domain>/mcp",
      "headers": {
        "Authorization": "Bearer vm_st_prod_service_token"
      }
    }
  }
}
```

Можно подключить разные account/token пары к разным серверам или использовать разные bearer-токены для разных записей в `mcpServers`.

Bearer-токен должен храниться только в локальном `mcp.json` пользователя или в секретах CI, но не в репозитории. Vetmanager `domain` и `api_key` должны храниться только внутри storage-слоя сервиса в зашифрованном виде.

## MCP-инструменты

Инструменты работают по bearer-only контракту: runtime credentials берутся только из `Authorization: Bearer <service_token>`, а Vetmanager credentials резолвятся через account context. Параметры `limit` (1–100) и `offset` (0–10 000) защищены от случайных массовых выборок.

### Контракт `tools/list`

MCP-клиенты могут использовать `tools/list` как источник истины по возможностям сервера.
Для каждого зарегистрированного инструмента сервер публикует:

- `name`
- `description`
- `inputSchema`

`description` формируется из актуальных docstrings инструментов и не должен
содержать runtime credentials. Начиная с этапа 18 descriptions также включают
доменные синонимы из справочника сущностей Vetmanager, чтобы LLM лучше
сопоставлял пользовательские формулировки вроде `хозяин`, `запись на приём`,
`приходная накладная`, `остаток на складе` с правильными MCP-инструментами.
`inputSchema` отражает реальные типы аргументов и ограничения вроде `limit: 1..100`.

### Универсальные sort/filter для list GET

Во всех list `get_*` инструментах поддерживаются дополнительные параметры:

- `sort`: массив объектов `{"property":"<field>","direction":"ASC|DESC"}`
- `filter`: массив объектов `{"property":"<field>","value":<value>,"operator":"<op>"}`

Поддерживаемые операторы фильтра:

- `=`, `!=`, `<>`
- `<`, `<=`, `>`, `>=`
- `in`, `not in` (`value` должен быть массивом)
- `like`

Пример:

```json
{
  "limit": 20,
  "offset": 0,
  "sort": [{"property": "id", "direction": "DESC"}],
  "filter": [{"property": "id", "value": 10, "operator": ">="}]
}
```

### Глобальные уведомления `messages/*`

Добавлены операционные инструменты для внутренних уведомлений Vetmanager:

- `send_message_to_all(message, campaign)`
- `send_message_to_users(message, campaign, user_ids)`
- `send_message_to_roles(message, campaign, roles)`
- `get_message_reports(limit, offset, campaign="", sort=None, filter=None)`

`get_message_reports` поддерживает обычный list-контракт `limit/offset/sort/filter`
и дополнительный query-параметр `campaign`, потому что этот сценарий нужен для
получения статуса конкретной рассылки.

### Кеширование GET-запросов

- Все успешные GET-запросы к Vetmanager API кешируются in-memory на **15 минут**.
- Ключ кеша: `METHOD + canonical_full_url_with_sorted_query + api_key_hash + account_id`.
- `api_key_hash` — отпечаток (`sha256`) API-ключа, изолирует кеш между разными ключами.
- `account_id` — добавлен с этапа 54.2.3 для строгой изоляции между аккаунтами
  даже при случайном совпадении api_key. Fallback на `none` для legacy caller'ов
  без account-контекста.
- Кеш-tag: `domain:entity`, где `entity` берётся из пути `/rest/api/<entity>/...`.
- После успешного `POST`/`PUT`/`DELETE` кеш для соответствующего тега `domain:entity` инвалидируется.
- Ограничение подхода: кеш живёт только в памяти процесса и полностью сбрасывается при рестарте сервера.

**105 инструментов** по 13 группам сущностей:

| Группа | Инструменты | Кол-во |
|--------|-------------|--------|
| Client | `get_clients`, `get_debtors`, `get_client_by_id`, `create_client`, `update_client`, `delete_client`, `get_client_profile`, `get_inactive_clients` | 8 |
| Pet | `get_pets`, `get_pet_by_id`, `create_pet`, `update_pet`, `delete_pet`, `get_pet_profile`, `get_inactive_pets` | 7 |
| Admission | `get_admissions`, `get_admission_by_id`, `create_admission`, `update_admission`, `get_client_upcoming_visits`, `get_daily_schedule` | 6 |
| MedicalCard | `get_medical_cards`, `get_medical_cards_by_client_id`, `get_medical_card_by_id`, `create_medical_card`, `update_medical_card`, `get_vaccinations` | 6 |
| Invoice | `get_invoices`, `get_average_invoice`, `get_invoice_by_id`, `create_invoice`, `update_invoice`, `delete_invoice` | 6 |
| Finance | `get_payments`, `get_payment_by_id`, `get_invoice_documents`, `get_invoice_document_by_id`, `add_invoice_document`, `delete_invoice_document`, `get_closing_of_invoices`, `get_closing_of_invoice_by_id`, `get_cassas`, `get_cassa_by_id`, `get_cassa_closes`, `get_cassa_close_by_id` | 12 |
| Good | `get_goods`, `get_good_by_id`, `create_good`, `update_good` | 4 |
| User | `get_users`, `get_user_by_id`, `update_user` | 3 |
| Warehouse | `get_good_groups`, `get_good_group_by_id`, `get_good_sale_params`, `get_good_sale_param_by_id`, `get_party_accounts`, `get_party_account_by_id`, `get_party_account_docs`, `get_party_account_doc_by_id`, `get_store_documents`, `get_store_document_by_id`, `get_suppliers`, `get_supplier_by_id`, `create_supplier`, `update_supplier`, `get_good_stock_balance` | 15 |
| Clinical | `get_hospitalizations`, `get_hospitalization_by_id`, `create_hospitalization`, `update_hospitalization`, `get_hospital_blocks`, `get_hospital_block_by_id`, `get_diagnoses` | 7 |
| Reference | `get_breeds`, `get_breed_by_id`, `get_pet_types`, `get_pet_type_by_id`, `get_cities`, `get_city_by_id`, `get_city_types`, `get_streets`, `get_street_by_id`, `get_units`, `get_unit_by_id`, `get_roles`, `get_role_by_id`, `get_user_positions`, `get_user_position_by_id`, `get_combo_manual_names`, `get_combo_manual_name_by_id`, `get_combo_manual_items`, `get_combo_manual_item_by_id` | 19 |
| Operations | `get_clinics`, `get_clinic_by_id`, `get_timesheets`, `get_timesheet_by_id`, `create_timesheet`, `get_properties`, `get_anonymous_clients`, `send_message_to_all`, `send_message_to_users`, `send_message_to_roles`, `get_message_reports` | 11 |
| Schedule | `get_doctor_free_slots` | 1 |

Payment REST API доступен только на чтение: Vetmanager Payment entity разрешает `restList`/`restView`, поэтому MCP не публикует `create_payment`.

### Ограничения CRUD по API

Некоторые операции запрещены контроллерами Vetmanager REST API:

| Сущность | Запрещено | Причина |
|----------|-----------|---------|
| Admission | DELETE | явно запрещён в filterRestAccessRules |
| MedicalCards | DELETE | явно запрещён в filterRestAccessRules |
| Payment | CREATE, UPDATE, DELETE | только restList + restView |
| Hospital | CREATE, DELETE | явно запрещены |
| User | CREATE, DELETE | явно запрещены |
| Suppliers | DELETE | не в whitelist |
| Cassa, PartyAccount, StoreDocument, Properties, HospitalBlock | CUD | только чтение |

Полная матрица: `artifacts/api_crud_permissions-ru.md`.

## MCP Prompts

**20 готовых шаблонов** для типовых сценариев — LLM использует их для составления цепочек вызовов инструментов:

Prompts работают по тому же bearer-only контракту, что и tools:
они принимают только бизнес-параметры сценария. Runtime credentials не
передаются в prompt arguments и не должны прокидываться в tool calls.

| Категория | Промпты |
|-----------|---------|
| Администратор | `daily_schedule`, `find_client`, `client_balance`, `book_appointment`, `create_invoice_prompt`, `doctor_workload`, `unconfirmed_appointments` |
| Врач | `pet_history`, `last_vaccinations`, `add_medical_note`, `current_inpatients`, `pet_invoices`, `pet_full_profile` |
| Финансы | `daily_revenue`, `unpaid_invoices`, `popular_services` |
| Склад и клиентская база | `search_good`, `low_stock`, `new_clients`, `client_no_visit` |

## Product metrics (ad-hoc report)

Для быстрого ответа на «сколько живых аккаунтов, кто мёртв, сколько токенов выдано, какие failures» — `/product-metrics` skill + `scripts/product_metrics_report.py`. Запускается on-demand через SSH → `docker compose exec mcp`.

Примеры:
```
/product-metrics                              # default 30-day window, top-10
/product-metrics --window-days=7 --top-n=5    # последние 7 дней
/product-metrics --format=json                # машинно-читаемый
```

Метрики (не покидают prod-сервер при обычном просмотре; email маскируются `al***@ex***.com` — маскирование снижает случайный disclosure, но это не анонимизация: в небольшой customer base и при characteristic доменах результат остаётся частично re-identifiable. Отчёт предназначен для owner-local просмотра):
- **Accounts**: total / new 24h-7d-30d / live (req within 7d) / dead (reg>30d, 0 req in 30d) / no tokens / no active connection + dead-accounts table.
- **Tokens**: active / expiring in 7d / issued 24h / revoked 24h-7d.
- **Requests**: total 24h-7d-30d + top-N accounts by 30d request count.
- **Failures** (24h / 7d / 30d breakdown): rate_limited, revoked, expired, ip_denied, no_scopes, no_connection.

Параллельно в Prometheus-expose'е `/metrics` копится `vetmanager_business_events_total{event=...}` counter для будущих Grafana-дашбордов без изменения кода.

## CI/CD

| Воркфлоу | Триггер | Что делает |
|----------|---------|------------|
| `test.yml` | push / pull request → main | два обязательных contour job: `fast` и `default` |
| `test-real.yml` | вручную (`workflow_dispatch`) | `opt_in_real` contour: real API e2e и opt-in real browser tests |
| `deploy-prod.yml` | автоматически после успешного `test.yml` на main | rsync кода на сервер, docker build, restart, smoke checks |

Добавить secrets для real tests:
- `VETMANAGER_TEST_API_KEY`
- опционально `VETMANAGER_TEST_USER_TOKEN`
- либо `VETMANAGER_TEST_USER_LOGIN` и `VETMANAGER_TEST_USER_PASSWORD`
- для real browser tests дополнительно включать `RUN_REAL_BROWSER_TESTS=1`

## Артефакты

| Путь | Назначение |
|------|------------|
| `artifacts/prd-vetmanager-mcp-ru.md` | Требования к продукту: видение, цели, персоны, функциональные и нефункциональные требования |
| `artifacts/technical-requirements-vetmanager-mcp-ru.md` | Технические требования: архитектура, стек, структура проекта |
| `artifacts/api_entity_reference-ru.md` | Справочник по сущностям Vetmanager API (38 сущностей) |
| `artifacts/api_crud_permissions-ru.md` | Матрица разрешённых CRUD-операций по Vetmanager REST API |
| `artifacts/api-research-notes-ru.md` | Накопленные неочевидные знания об API (чеклист полей, filter operators, edge cases) — читать перед work with admission/pet/medical_card/timesheet |
| `artifacts/vetmanager_openapi_v6.json` | Спецификация OpenAPI v6 для Vetmanager REST API |
| `artifacts/vetmanager_postman_collection.json` | Коллекция Postman для ручного тестирования |
| `artifacts/review/*.md` | Периодические deep-review (super-review) отчёты с findings + Codex arbitration |
| `artifacts/security-deployment-notes-vetmanager-mcp-ru.md` | Чек-лист для production deploy'я (если присутствует) |
| `artifacts/observability-runbook-vetmanager-mcp-ru.md` | Runbook для операций с метриками и логами (если присутствует) |
| `artifacts/operations-readiness-vetmanager-mcp-ru.md` | Go/No-Go чеклист готовности к прод (если присутствует) |
| `artifacts/release-checklist-vetmanager-mcp-ru.md` | Регламент релиза (если присутствует) |

## Self-hosted / Развернуть у себя

Этот проект — **open-source**. Вы можете развернуть собственный экземпляр MCP-сервера для вашей клиники или организации.

Что нужно:
1. Сервер с Docker (любой VPS/dedicated)
2. Домен с DNS A-record на IP сервера
3. SSH-доступ к серверу

```bash
git clone https://github.com/otis22/vetmanager-mcp.git
cd vetmanager-mcp
./scripts/init_server.sh root@<your-server-ip>
./scripts/deploy_server.sh root@<your-server-ip>
```

Скрипт `init_server.sh` автоматически настроит Docker, PostgreSQL, Nginx reverse proxy и TLS-сертификат через Let's Encrypt. Подробнее — в секции [Деплой на сервер](#деплой-на-сервер).

## Contributing

Проект открыт для контрибуций. Если вы нашли баг или хотите предложить улучшение:

- [Открыть issue](https://github.com/otis22/vetmanager-mcp/issues)
- [Security-уязвимости](SECURITY.md) — сообщайте приватно

Перед отправкой PR убедитесь, что тесты проходят: `docker compose --profile test run --rm test`.

## License

[MIT](LICENSE)
