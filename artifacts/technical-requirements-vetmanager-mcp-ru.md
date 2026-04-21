# Технические требования: Vetmanager MCP Server

**Автор:** Manus AI  
**Актуализировано:** 23 марта 2026 г.

## 1. Введение

Документ фиксирует текущую техническую архитектуру проекта `vetmanager-mcp`
и ближайшую целевую эволюцию, уже отражённую в `Roadmap.md`.
Он используется как справочный артефакт при декомпозиции задач, проверке
согласованности решений и развитии MCP-инструментов поверх Vetmanager REST API.

Проект реализован как stateless MCP-сервер, который:
- работает по HTTP transport (`streamable-http`);
- принимает runtime credentials только через `Authorization: Bearer <service_token>`;
- преобразует tool calls в запросы к Vetmanager REST API;
- поддерживает мультитенантность, базовое кеширование, pacing запросов и
  security hardening.

Текущая эволюция проекта по roadmap этапам 20–104:
- bearer-only runtime-контракт уже реализован;
- web-контур с лендингом, регистрацией и кабинетом аккаунта;
- хранение Vetmanager-интеграции на уровне аккаунта;
- выпуск нескольких Bearer-токенов с TTL, revoke и учётом использования;
- поддержка двух Vetmanager auth modes: `domain + rest_api_key` и
  `user login/password -> user token`;
- convenience-инструменты: `get_inactive_clients`, `get_inactive_pets`,
  `get_client_upcoming_visits`, `get_daily_schedule`, `get_doctor_free_slots`;
- ergonomic filters: нормализованный поиск по телефону через
  `/rest/api/ClientPhone`, `payment_status` параметр `get_invoices`,
  `status IN` batch-фильтры;
- observability core (этап 88): correlation_id в upstream headers,
  per-tool latency+outcome метрики, upstream latency histogram,
  structured warnings на timeout/network error;
- security hot-fix (этап 89): pattern-based Sentry sanitizer,
  SITE_BASE_URL env для self-hosted deployments;
- VM client overhaul (этап 91): shared httpx.AsyncClient singleton с
  keep-alive pool, exponential-backoff retry на 429/502/503/504,
  split timeouts, per-domain circuit breaker с single-probe HALF_OPEN,
  новое исключение `VetmanagerUpstreamUnavailable`;
- FilterBuilder (этап 93): typed `Filter` dataclass + helpers eq/in_/
  like/etc.; `build_list_query_params` accepts `list[Filter]`;
- performance polish (этап 95): PBKDF2 через `asyncio.to_thread`,
  `paginate_all` default `max_rows=10_000`, partial-failure tolerance
  в `get_client_profile` через `asyncio.gather(return_exceptions=True)`;
- workflow discipline (этап 104): pre-commit + commit-msg git hooks,
  `lint_api_contracts.py` для phantom field / phantom enum detection,
  `check_stage_completion.sh` и `update_review_status.py`,
  subagent pre-return checklists;
- post-review hot-fix (этап 96): `update_admission` payload mapping +
  `get_client_profile::next_admission` status IN-tuple + CancelledError
  propagation + breaker probe clearance на 4xx + `filters.in_([])`
  reject + `_parse_retry_after` DoS mitigation.

## 2. Технологический стек

| Компонент | Технология | Актуальное состояние | Назначение |
|---|---|---|---|
| Язык | Python | 3.11+ | Основной язык сервера и инструментов |
| Базовый образ | `python:3.12-slim` | используется в `Dockerfile` | Сборка и запуск контейнера |
| MCP framework | `fastmcp` | `>=3.1.0,<4` | Регистрация tools/prompts и запуск MCP HTTP server. Мажор 3.x несовместим с 2.x (убран public `call_tool` в 2.14.x). |
| HTTP client | `httpx` | `>=0.27.0` | Запросы к billing API и Vetmanager API |
| Тесты | `pytest`, `pytest-asyncio`, `respx` | через Docker test profile | Unit, mock e2e, real e2e |
| Контейнеризация | Docker + Compose | обязательный runtime | Локальный запуск, тесты, деплой |

Примечания:
- Хост-машина не обязана иметь установленный Python toolchain.
- Установка зависимостей происходит внутри контейнера через `pip`.
- Текущий проект не использует `uv`, `.venv`, `requirements.txt` или `config.py`.

## 3. Архитектура и модель запуска

### 3.0. Статус документа

Разделы ниже делятся на два слоя:
- текущее состояние реализации, уже находящееся в кодовой базе;
- будущие этапы roadmap, которые ещё не доведены до production-grade maturity.

Если возникает конфликт, источником истины для текущего runtime-контракта
остаются код и README. Bearer-only архитектура уже реализована и описывает
актуальное состояние проекта.

### 3.1. Обязательная модель запуска

1. Сервер и тесты запускаются только через `docker compose`.
2. Runtime credentials не хранятся в репозитории и не задаются через проектный `.env`.
3. Для рабочего MCP-контура credentials приходят только через:
   - `Authorization: Bearer <service_token>`
4. Web-контур (`/register`, `/login`, `/account`) работает через signed session cookie.
5. Контейнеры запускаются с UID/GID хоста для корректной работы с bind mounts.

### 3.2. Основные компоненты

#### MCP server (`server.py`)

Отвечает за:
- инициализацию `FastMCP`;
- регистрацию всех tools и prompts;
- запуск HTTP transport с параметрами:
  - `MCP_TRANSPORT=streamable-http`
  - `MCP_HOST`
  - `PORT`
  - `MCP_PATH`

Сервер публикует endpoint MCP по пути `/mcp` и предназначен для подключения
клиентов вроде Cursor/Claude через `url + Authorization: Bearer <service_token>`.

#### Description enrichment (`tool_descriptions.py`)

Модуль централизованно обогащает descriptions зарегистрированных MCP tools:
- использует доменные синонимы из справочного слоя проекта;
- дополняет descriptions после `register_all(mcp)`;
- делает `tools/list` более полезным для LLM без изменения бизнес-логики
  инструментов и без ручного редактирования десятков docstrings.

#### Vetmanager API client (`vetmanager_client.py` + `vm_transport/*`)

`VetmanagerClient` — thin orchestrator (создаётся на каждый MCP request
context), делегирующий в `vm_transport/` package (stage 103d). Инкапсулирует:
- чтение уже резолвленных Vetmanager credentials из bearer auth context;
- валидацию `domain` как subdomain;
- резолв базового host через billing API:
  `https://billing-api.vetmanager.cloud/host/{domain}`;
- allowlist-проверку резолвленного host;
- автоматическую подстановку `X-REST-API-KEY`;
- request pacing: минимум 50ms между последовательными исходящими запросами;
- нормализацию ошибок в исключения уровня приложения.

Структура `vm_transport/` (stage 103d):
- `pool.py` — per-loop shared `httpx.AsyncClient`, keep-alive pool (50/100,
  30s expiry), double-check locking на first-init;
- `breaker.py` — per-domain circuit breaker (closed/open/half_open),
  env-tunable thresholds (`BREAKER_FAILURE_THRESHOLD=5`, `WINDOW=60s`,
  `COOLDOWN=30s`);
- `retry.py` — retry policy: `MAX_RETRIES_READ=3`, `WRITE=0`, exponential
  backoff 0.2s×2^attempt с jitter, honours `Retry-After` (clamped к 300s);
- `cache_policy.py` — TTL tiering (`CACHE_TTL_SECONDS=900`, `SHORT=60`),
  entity-from-path routing.

#### Bearer auth resolution (`auth/*`, с BC shims на top-level)

Canonical location — `auth/` package (stage 103a). Top-level модули
`bearer_auth.py`, `vetmanager_auth.py`, `bearer_rate_limiter.py`,
`request_auth.py` — BC shim re-exports (≤22 LOC each).

Структура `auth/` package:
- `context.py` — `VetmanagerAuthContext` dataclass + auth-mode constants
  (`VETMANAGER_AUTH_MODE_*`, headers).
- `vetmanager.py` — `resolve_vetmanager_credentials(connection)` — connection →
  нормализованный auth context.
- `bearer.py` — `BearerAuthContext` + `_reject` helper + pipeline
  `resolve_bearer_auth_context` (6 failure branches, один audit-log-and-raise
  helper).
- `rate_limit.py` — `InMemoryBearerRateLimiter` + sliding-window limiter
  (default 1000 req/60s, env-tunable).
- `request.py` — `get_bearer_token()` header parser.

Контракт bearer auth:
- tools и prompts не принимают runtime credentials как аргументы;
- raw Bearer token используется только для lookup/hash-verify и не сохраняется в
  audit details или пользовательских ошибках;
- активное Vetmanager-подключение определяется на уровне аккаунта, а не через
  request headers;
- при отсутствии/некорректности Bearer токена сервер возвращает явную безопасную
  auth error.

#### Resource gateway (`resources/*`)

Stage 103c: entity-specific aggregate-profile composition вынесена в
`resources/` layer. Tools делегируют; resources владеют VM field names,
filter composition, response unwrapping.

- `resources/client_profile.py::fetch(client_id)` — 4-section композиция:
  client + invoices + admissions + next_admission (IN-filter с
  `ACTIVE_ADMISSION_STATUSES`).
- `resources/pet_profile.py::fetch(pet_id)` — 3-section: pet + MedicalCards
  (filter=patient_id) + vaccinations; плюс `last/next_vaccination_date`
  derivation.
- `resources/_aggregation.py::gather_sections` — shared partial-gather
  helper (structured section_errors, CancelledError re-raise,
  `aggregator_partial` warning log).
- `resources/admission_status.py::ACTIVE_ADMISSION_STATUSES` — canonical
  location (stage 106.3). `tools.admission` re-экспортит для BC.

Layering invariant: `resources/` НЕ импортит из `tools/`. Tools импортят
из resources/ вниз.

#### MCP tools (`tools/*.py`)

Инструменты реализованы статически, по одному или нескольким модулям на группу
сущностей Vetmanager API:
- `client.py`
- `pet.py`
- `admission.py`
- `medical_card.py`
- `invoice.py`
- `good.py`
- `user.py`
- `reference.py`
- `finance.py`
- `warehouse.py`
- `clinical.py`
- `operations.py`
- `schedule.py`
- `_inactive_helpers.py`
- `_slots_helpers.py`

Каждый tool:
- регистрируется через `@mcp.tool`;
- использует `VetmanagerClient`;
- принимает только бизнес-параметры;
- использует docstring и type hints для MCP schema/export;
- для list GET поддерживает `limit`, `offset`, а также общий контракт `sort/filter`.

Отдельно поддерживаются:
- агрегирующие инструменты вроде `get_client_profile` и `get_pet_profile`;
- специализированные endpoint-driven инструменты вроде `get_vaccinations`;
- операционные инструменты глобальных уведомлений `messages/*`.

#### MCP prompts (`prompts.py`)

Prompts регистрируются отдельно от tools и:
- реализуют типовые workflow-сценарии для LLM;
- работают по тому же bearer-only runtime-контракту, что и tools;
- не принимают runtime credentials;
- не должны подсказывать передачу credentials в tool calls.

Покрываемые сценарии включают:
- расписание и работу администратора;
- клинические сценарии врача;
- финансовую аналитику;
- складские и клиентские выборки.

#### Validation helpers (`validators.py`)

Содержит:
- валидацию безопасных лимитов массовых выборок;
- валидацию суммы платежа;
- экспорт `LimitParam` для корректной генерации `inputSchema`.

Stage 103.8: `build_list_query_params` переехал в `filters.py` (co-located с
Filter primitives); `validators.py` re-экспортит его для BC.

#### FilterBuilder (`filters.py`)

Canonical location для:
- `Filter` dataclass + helpers `eq/ne/lt/lte/gt/gte/in_/not_in/like`;
- `as_dict_list` для mixed `list[Filter | dict]`;
- `build_list_query_params(limit, offset, sort, filters, extra)` — builder
  для VM REST list-query params.

Stage 103.2: все 11 tool модулей используют `filters.*` вместо raw dict
literal'ов. Stage 106.4 (F6 fix): `extra` dict drops только None/empty
string; numeric zero сохраняется (privacy-safe — `client_id=0` не silently
драпается в full-scan).

#### Cache layer (`request_cache.py`)

Реализует process-local in-memory cache:
- TTL 900s по умолчанию;
- короткий TTL для “горячих” сущностей;
- ключ: `METHOD + canonical_full_url_with_query + api_key_hash + account_id`;
- теги вида `domain:entity`;
- инвалидация по тегу после `POST` / `PUT` / `DELETE`.

#### `tools/list` contract

Сервер рассматривает `tools/list` как source of truth по своим возможностям.
Для каждого инструмента экспортируются:
- `name`;
- `description`;
- `inputSchema`.

Дополнительные требования текущей реализации:
- `description` строится из docstring и может обогащаться доменными синонимами;
- `inputSchema` отражает реальные типы и ограничения, включая safety-границы
  для `limit` и ограничения непустых массивов там, где это критично.

### 3.3. Структура проекта

Актуальная структура репозитория (после stages 103a/c/d):

```text
vetmanager-mcp/
├── AGENTS.md
├── CLAUDE.md
├── Roadmap.md
├── AssumptionLog.md
├── PRD/
├── artifacts/
│   └── review/                 # super-review reports + dismissed-findings index
├── auth/                       # auth package (stage 103a)
│   ├── __init__.py
│   ├── context.py              # VetmanagerAuthContext + mode constants
│   ├── vetmanager.py           # resolve_vetmanager_credentials
│   ├── bearer.py               # BearerAuthContext + resolve_bearer_auth_context + _reject
│   ├── rate_limit.py           # InMemoryBearerRateLimiter + BEARER_RATE_LIMITER
│   └── request.py              # get_bearer_token header parser
├── vm_transport/               # transport layer (stage 103d)
│   ├── __init__.py
│   ├── pool.py                 # per-loop shared httpx.AsyncClient
│   ├── breaker.py              # per-domain circuit breaker
│   ├── retry.py                # parse_retry_after + backoff_seconds
│   └── cache_policy.py         # TTL tiering + entity_from_path
├── resources/                  # entity gateways (stage 103c / 106.3)
│   ├── __init__.py
│   ├── _aggregation.py         # gather_sections partial-gather helper
│   ├── admission_status.py     # ACTIVE_ADMISSION_STATUSES canonical
│   ├── client_profile.py       # get_client_profile fetch impl
│   └── pet_profile.py          # get_pet_profile fetch impl
├── tools/                      # MCP tool registrations
│   ├── schedule.py             # get_doctor_free_slots
│   ├── _inactive_helpers.py    # inactive client/pet batching helpers
│   └── _slots_helpers.py       # free-slot interval math
├── tests/
├── scripts/
├── alembic/
├── server.py
├── vetmanager_client.py        # thin orchestrator over vm_transport/*
├── bearer_auth.py              # BC shim (13 LOC) — re-exports auth.bearer
├── vetmanager_auth.py          # BC shim (19 LOC) — re-exports auth.context + auth.vetmanager
├── bearer_rate_limiter.py      # BC shim (22 LOC) — re-exports auth.rate_limit
├── request_auth.py             # BC shim (7 LOC) — re-exports auth.request
├── request_credentials.py      # legacy shim (11 tests still patch it here)
├── request_cache.py
├── filters.py                  # FilterBuilder + build_list_query_params
├── validators.py               # validators + build_list_query_params BC re-export
├── prompts.py
├── tool_descriptions.py
├── exceptions.py
├── service_metrics.py          # Prometheus metrics + instrument_call
├── observability_logging.py
├── structured_logging.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── pytest.ini
└── README.md
```

**Layering invariant (stage 106.3):** `tools/` → `resources/` → `vm_transport/` + `auth/` → storage. Вверх импортировать запрещено.

### 3.4. Аутентификация и конфигурация

#### Runtime contract

Рабочий контур использует только bearer-only схему:

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

Правила:
- runtime credentials не передаются в аргументах tools/prompts;
- `Authorization: Bearer <service_token>` является единственным runtime-входом
  в MCP-контур;
- Vetmanager credentials хранятся в активном `vetmanager_connection`
  конкретного аккаунта;
- `TEST_DOMAIN` / `TEST_API_KEY` и другие `TEST_*` допустимы только для
  opt-in real tests;
- один экземпляр сервера обслуживает разные аккаунты и клиники без перезапуска.

#### Host resolution

При первом обращении внутри `VetmanagerClient`:
1. из account-based auth context читается активный Vetmanager auth mode;
2. для mode `domain + rest_api_key` из connection читается `domain`;
3. выполняется `GET https://billing-api.vetmanager.cloud/host/{domain}`;
4. из ответа извлекается clinic-specific base URL;
5. URL проходит HTTPS и allowlist проверку;
6. результат кешируется в экземпляре клиента.

### 3.5. Bearer-only архитектура и web-контур

Текущая модель сервиса:
- пользователь регистрирует аккаунт сервиса;
- аккаунт настраивает один активный способ авторизации в Vetmanager;
- аккаунт выпускает один или несколько Bearer-токенов сервиса;
- MCP-клиенты используют только `Authorization: Bearer <service_token>`;
- сервис по Bearer находит аккаунт и применяет настроенный Vetmanager auth mode.

Реализованные компоненты:
- web-слой с лендингом, регистрацией, логином и кабинетом;
- storage для аккаунтов, интеграций и Bearer-токенов;
- auth context на основе аккаунта вместо headers-only credentials;
- usage accounting для токенов (`last_used_at`, `request_count`);
- abstraction layer для нескольких способов авторизации в Vetmanager.

Контракт `login/password -> user token` для web-контура:
- exchange выполняется через `POST /token_auth.php`;
- request body: `multipart/form-data`;
- поля exchange: `login`, `password`, `app_name`;
- `app_name` фиксирован как `vetmanager-mcp`;
- `X-REST-API-KEY` в exchange-запросе не используется;
- после exchange в storage сохраняется только `user_token`.

Ключевые сущности storage-модели:
- `account`
- `vetmanager_connection`
- `service_bearer_token`
- `token_usage_stats` или `token_usage_log`

Ограничения текущей модели:
- Bearer-токены привязываются к аккаунту;
- у аккаунта один активный Vetmanager auth mode в каждый момент времени;
- dual-mode MCP runtime не планируется;
- runtime enforcement scopes пока не включён;
- scope metadata уже может храниться на токене для будущего ограничения прав.

### 3.6. Future token scopes / capability model

Подготовленная модель прав строится вокруг capability list на уровне токена:
- права принадлежат Bearer-токену, а не аккаунту целиком;
- scope именуется как `<resource_group>.<action>`;
- отсутствие scope в будущем трактуется как запрет;
- legacy токены без scope manifest остаются совместимыми как full-access tokens,
  пока enforcement не включён.

Coarse-grained scopes первого итерационного релиза:
- `clients.read`
- `clients.write`
- `pets.read`
- `pets.write`
- `admissions.read`
- `admissions.write`
- `medical_cards.read`
- `medical_cards.write`
- `finance.read`
- `finance.write`
- `inventory.read`
- `inventory.write`
- `users.read`
- `messaging.read`
- `messaging.write`
- `reference.read`
- `analytics.read`

Storage preparation:
- `service_bearer_tokens.access_policy_version` хранит версию policy schema;
- `service_bearer_tokens.scopes_json` хранит сериализованный scope manifest;
- новые токены получают default full-access manifest для обратной совместимости.

## 4. Детали реализации

### 4.1. Реализация tools

Инструменты реализуются вручную, а не кодогенерацией из OpenAPI.

Причины:
- лучшее качество docstrings;
- более понятные сигнатуры для LLM;
- явный контроль над валидацией, фильтрами, aliases полей и safety-guardrail’ами.

Каждый list tool по возможности использует единый helper `build_list_query_params()`
и поддерживает:
- `limit` от 1 до 100;
- `offset` от 0 до 10 000;
- `sort` в формате Vetmanager API;
- `filter` в формате Vetmanager API.

Кроме CRUD/list-инструментов, проект поддерживает:
- агрегирующие профили клиента и питомца;
- извлечение вакцинаций питомца через специальный endpoint;
- глобальные уведомления `messages/all`, `messages/users`,
  `messages/reports`, `messages/roles`.

### 4.2. Обработка ошибок

Используются специализированные исключения из `exceptions.py`, включая:
- `VetmanagerError`
- `AuthError`
- `NotFoundError`
- `HostResolutionError`
- `VetmanagerTimeoutError`

Требования к ошибкам:
- сообщение должно быть пригодным для LLM и пользователя;
- секреты должны быть замаскированы;
- ошибки сети, auth и 404 должны различаться явно.

### 4.3. Безопасность

Обязательные ограничения:
- строгая проверка `domain` по regex subdomain;
- только HTTPS для резолвленного host;
- allowlist доменных суффиксов Vetmanager;
- отсутствие raw API key в логах и ошибках;
- отсутствие raw Bearer token и `token_hash` в audit log и пользовательских ошибках;
- отсутствие runtime credentials в репозитории;
- безопасные лимиты на list операции и суммы платежей;
- rate limiting по `bearer_token_id` (1000 req/60s по умолчанию) до обновления usage accounting;
- per-email login lockout: 10 попыток за 15 минут (namespace `login_lockout`);
- per-email registration rate limit: 3 попытки за 1 час (namespace `register_email`);
- per-IP rate limiting для web endpoints;
- token-centric audit trail для lifecycle и runtime auth events;
- cleanup expired токенов с переходом в статус `expired`;
- signed web session cookie c `HttpOnly`, `Secure` и `SameSite=Strict` по умолчанию;
- session timeout: 24 часа (настраиваемо через `WEB_SESSION_MAX_AGE_SECONDS`);
- обязательный `WEB_SESSION_SECRET` или fallback на `STORAGE_ENCRYPTION_KEY`
  без встроенного dev-secret;
- password hashing: PBKDF2-HMAC-SHA256 с salt, минимум 10 символов, uppercase + lowercase + цифра;
- CSRF: double-submit cookie с HMAC-SHA256 подписью, TTL 2 часа;
- future scope policy хранится отдельно от raw token и не требует хранения
  дополнительных секретов;
- pre-deploy backup production PostgreSQL через `scripts/backup_postgres.sh`
  (`pg_dump` + timestamped rollback point);
- post-deploy integrity check: успешный smoke и readiness после применения
  миграций/рестарта.

### 4.4. Производительность и кеширование

- Между последовательными HTTP-запросами к Vetmanager API действует минимальный gap 50ms.
- GET-запросы кешируются in-memory.
- Кеш изолирован по `api_key_hash`, чтобы не смешивать ответы разных tenants.
- После мутаций выполняется tag invalidation по `domain:entity`.

## 5. Тестирование

Проект использует три уровня проверки:

### 5.1. Unit tests

Покрывают:
- bearer auth resolution и runtime auth context;
- multitenancy и security ограничения клиента;
- validation helpers;
- schema/export contracts;
- prompts и enriched descriptions.

### 5.2. Mock e2e / contract tests

Запускаются через `respx` и проверяют:
- маршрутизацию к billing API и Vetmanager API;
- корректность HTTP payload/query params;
- поведение агрегирующих инструментов;
- ключевые safety, auth audit и cache сценарии;
- web account flow, token issue/revoke и cleanup-поведение.

### 5.3. Real API e2e tests

Требуют:
- `TEST_DOMAIN`
- `TEST_API_KEY`

Используются как smoke/integration уровень против живого API.

Дополнительно поддерживается opt-in real contour для `login/password -> user token`
и production/browser verification через `TEST_USER_TOKEN` или
`TEST_USER_TOKEN_BASE_URL` + `TEST_USER_LOGIN` + `TEST_USER_PASSWORD`.

### 5.4. Способ запуска

Основная команда проекта:

```bash
docker compose --profile test run --rm test
```

## 6. Развёртывание и эксплуатация

### 6.1. Локальный запуск

```bash
cp .env.example .env
docker compose build
docker compose up -d
```

### 6.2. Прод-подобный режим

Сервер публикуется как HTTP MCP endpoint и может быть подключён внешним MCP-клиентом
через `url + Authorization: Bearer <service_token>`.

### 6.3. Деплой

Проект содержит операционные скрипты:
- `scripts/init_server.sh`
- `scripts/deploy_server.sh`
- `scripts/sync_and_deploy_server.sh`

Поддерживаются:
- первичная настройка хоста;
- деплой по SSH;
- rsync-based деплой для приватного репозитория;
- TLS через nginx + certbot;
- GitHub Actions deploy pipeline.

## 7. Ограничения и принципы

- Проект остаётся stateless на уровне runtime-сервера.
- Кеш process-local и не разделяется между инстансами.
- Все управленческие артефакты ведутся вручную в Markdown:
  `Roadmap.md`, `PRD/*.md`, `AssumptionLog.md`.
- Поведение Vetmanager API не домысливается и должно сверяться по OpenAPI и
  `api_entity_reference-ru.md`.

## 7.1. Журнал этапов 97-121 (stage 127 backfill)

Компактный changelog пропущенных в §2 этапов:
- **97** — Docs + workflow compliance backfill.
- **98** — Observability hardening (structured logs, correlation_id propagation).
- **99** — Reliability hardening II: breaker env-tunable thresholds, shared httpx pool per-loop.
- **100** — Security hardening II: timing-safe auth, dummy hash verify.
- **101** — Tests hardening II: stage91/96 private-attr reads via public API.
- **102** — Product consistency sweep: aggregator section_errors structured shape.
- **103a/c/d** — Architecture consolidation: auth package split, resources/ gateway layer, vm_transport/* split из `vetmanager_client.py`.
- **104** — Workflow discipline (self-attestation checklist rule).
- **105** — Blocker hotfix: breaker amplification fix (1 failure per logical call, not per retry).
- **106** — High-severity reliability + docs hardening (probe_in_flight finally cleanup; test-patch stability).
- **107** — Observability gaps: auth-path logs, billing metric, retry trace, aggregator correlation_id.
- **108** — Code quality cleanup: builtin shadow, duplication, inline imports.
- **109** — Test brittleness + BC invariants (closed 5 deferred subtasks; stage 109 full subset `done`).
- **109.10** — parallel vm_upstream_network_error test.
- **110** — Product metrics: ad-hoc CLI `scripts/product_metrics_report.py` + business events counter + `/product-metrics` skill.
- **111** — Blocker cleanup (super-review 2026-04-19): `/metrics` auth gate via `METRICS_AUTH_TOKEN` + nginx allow/deny, composite index на `token_usage_logs(event_type, event_at)`, login lockout metric, `record_business_event` ERROR log on unknown event_name.
- **112** — Observability integrity: `circuit_breaker_opened` log, integration save failure log+metric, url_path → entity scrub, correlation_id explicit in business-event logs, retry log DEBUG.
- **113** — Resilience completeness (focused): billing-api per-loop AsyncClient + TTL cache + integrated shutdown hook; breaker env accessors. 113.2-113.5 deferred to stage 113b.
- **114** — Simplicity debt (focused F2): inline imports cleanup в `service_metrics.py` + `resources/_aggregation.py`; AST regression test.
- **115** — Real concurrency tests: breaker amplification (gather + Event barrier), pool singleton identity; autouse `reset_service_metrics` fixture.
- **116** — PRD 110 completion: `--window-days` CLI flag removed (half-wired), `tokens.expired_auto_24h` counter added, PRD 110 docs drift fixed, AssumptionLog commit SHAs backfilled.
- **117** — Docs catchup: compact changelog/backfill, observability runbook banner, README observability drift cleanup, workflow-check `(pending)` detector.
- **118** — Product metrics correctness follow-up: timezone-aware `--now-override` и UTC-consistent `dead_list.last_request_at`.
- **119** — Test isolation + workflow/docs cleanup: `REQUEST_CACHE.metrics` reset в fixtures, AssumptionLog SHA backfill, release checklist sync.
- **120** — Historical PRD goal-section backfill: старые PRD приведены к текущему workflow contract через `## Цель`.
- **121** — Roadmap status sync cleanup: внутренние подпункты закрытых этапов выровнены к фактическому `done`.

### Дополнительная структура
- `scripts/` — операционные + ad-hoc: `init_server.sh`, `deploy_server.sh`, `sync_and_deploy_server.sh`, `backup_postgres.sh`, `review_workflow_check.sh`, `product_metrics_report.py`.
- `.claude/commands/` — skill-файлы (`product-metrics`, `super-review`).
- `artifacts/review/` — накопленные super-review отчёты + `inadequate-findings-index.md`.

### Резидентные upstream'ы
- `vm_transport/breaker.py` — per-domain breaker для `*.vetmanager.cloud` clinics.
- `host_resolver.py` (stage 113.F7) — shared per-loop `httpx.AsyncClient` + TTL cache для billing-api.

### Observability metrics (stage 88 + 110)
- `vetmanager_upstream_requests_total{target,status}` + latency histogram;
- `vetmanager_tool_calls_total{endpoint,method,outcome}` + latency histogram;
- `vetmanager_business_events_total{event}` — 4 allowed events.

## 8. Ссылки

1. [Документация Vetmanager REST API](https://help.vetmanager.cloud/article/3029)
2. [Model Context Protocol](https://modelcontextprotocol.io/)
3. [Спецификация Vetmanager OpenAPI v6](./vetmanager_openapi_v6.json)
