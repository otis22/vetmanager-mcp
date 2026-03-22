# Технические требования: Vetmanager MCP Server

**Автор:** Manus AI  
**Актуализировано:** 21 марта 2026 г.

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

Текущая эволюция проекта по roadmap этапов 20–28:
- bearer-only runtime-контракт уже реализован;
- web-контур с лендингом, регистрацией и кабинетом аккаунта;
- хранение Vetmanager-интеграции на уровне аккаунта;
- выпуск нескольких Bearer-токенов с TTL, revoke и учётом использования;
- поддержка двух Vetmanager auth modes: `domain + rest_api_key` и
  `user login/password -> user token`.

## 2. Технологический стек

| Компонент | Технология | Актуальное состояние | Назначение |
|---|---|---|---|
| Язык | Python | 3.11+ | Основной язык сервера и инструментов |
| Базовый образ | `python:3.12-slim` | используется в `Dockerfile` | Сборка и запуск контейнера |
| MCP framework | `fastmcp` | `>=2.0.0` | Регистрация tools/prompts и запуск MCP HTTP server |
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

#### Vetmanager API client (`vetmanager_client.py`)

`VetmanagerClient` создаётся на каждый MCP request context и инкапсулирует:
- чтение уже резолвленных Vetmanager credentials из bearer auth context;
- валидацию `domain` как subdomain;
- резолв базового host через billing API:
  `https://billing-api.vetmanager.cloud/host/{domain}`;
- allowlist-проверку резолвленного host;
- автоматическую подстановку `X-REST-API-KEY`;
- request pacing: минимум 50ms между последовательными исходящими запросами;
- retry/timeout поведение;
- нормализацию ошибок в исключения уровня приложения;
- in-memory tagged cache для GET-запросов.

#### Bearer auth resolution (`bearer_auth.py`)

Модуль резолвит `Authorization: Bearer <service_token>` в account-specific
runtime context.

Контракт:
- tools и prompts не принимают runtime credentials как аргументы;
- raw Bearer token используется только для lookup/hash-verify и не сохраняется в
  audit details или пользовательских ошибках;
- активное Vetmanager-подключение определяется на уровне аккаунта, а не через
  request headers;
- при отсутствии/некорректности Bearer токена сервер возвращает явную безопасную
  auth error.

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
- работают по тому же headers-only контракту;
- не принимают `domain` / `api_key`;
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
- helper построения query params для list GET;
- экспорт `LimitParam` для корректной генерации `inputSchema`.

#### Cache layer (`request_cache.py`)

Реализует process-local in-memory cache:
- TTL 900s по умолчанию;
- короткий TTL для “горячих” сущностей;
- ключ: `METHOD + canonical_full_url_with_query + api_key_hash`;
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

Актуальная структура репозитория:

```text
vetmanager-mcp/
├── AGENTS.md
├── Roadmap.md
├── AssumptionLog.md
├── PRD/
├── artifacts/
├── tools/
├── tests/
├── scripts/
├── server.py
├── vetmanager_client.py
├── request_credentials.py
├── request_cache.py
├── validators.py
├── prompts.py
├── tool_descriptions.py
├── exceptions.py
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── pytest.ini
└── README.md
```

### 3.4. Аутентификация и конфигурация

#### Runtime contract

Рабочий контур использует только headers-only схему:

```json
{
  "mcpServers": {
    "vetmanager": {
      "url": "http://localhost:8000/mcp",
      "headers": {
        "X-VM-Domain": "myclinic",
        "X-VM-Api-Key": "your-rest-api-key"
      }
    }
  }
}
```

Правила:
- runtime Bearer token не передаётся в аргументах tools/prompts;
- `domain` и Vetmanager credential не задаются проектным `.env` для runtime;
- `TEST_DOMAIN` / `TEST_API_KEY` допустимы только для real e2e tests;
- один экземпляр сервера обслуживает разные клиники без перезапуска.

#### Host resolution

При первом обращении внутри `VetmanagerClient`:
1. из bearer auth context читается `domain`;
2. выполняется `GET https://billing-api.vetmanager.cloud/host/{domain}`;
3. из ответа извлекается clinic-specific base URL;
4. URL проходит HTTPS и allowlist проверку;
5. результат кешируется в экземпляре клиента.

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
- rate limiting по `bearer_token_id` до обновления usage accounting;
- token-centric audit trail для lifecycle и runtime auth events;
- cleanup expired токенов с переходом в статус `expired`;
- signed web session cookie c `HttpOnly`, `Secure` и `SameSite=Strict` по умолчанию;
- обязательный `WEB_SESSION_SECRET` или fallback на `STORAGE_ENCRYPTION_KEY`
  без встроенного dev-secret;
- future scope policy хранится отдельно от raw token и не требует хранения
  дополнительных секретов.

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

## 8. Ссылки

1. [Документация Vetmanager REST API](https://help.vetmanager.cloud/article/3029)
2. [Model Context Protocol](https://modelcontextprotocol.io/)
3. [Спецификация Vetmanager OpenAPI v6](./vetmanager_openapi_v6.json)
