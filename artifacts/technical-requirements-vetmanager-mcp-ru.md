# Технические требования: Vetmanager MCP Server

**Автор:** Manus AI  
**Актуализировано:** 21 марта 2026 г.

## 1. Введение

Документ фиксирует текущую техническую архитектуру проекта `vetmanager-mcp`.
Он используется как справочный артефакт при декомпозиции задач, проверке
согласованности решений и развитии MCP-инструментов поверх Vetmanager REST API.

Проект реализован как stateless MCP-сервер, который:
- работает по HTTP transport (`streamable-http`);
- принимает runtime credentials только через HTTP headers;
- преобразует tool calls в запросы к Vetmanager REST API;
- поддерживает мультитенантность, базовое кеширование, pacing запросов и
  security hardening.

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

### 3.1. Обязательная модель запуска

1. Сервер и тесты запускаются только через `docker compose`.
2. Runtime credentials не хранятся в репозитории и не задаются через проектный `.env`.
3. Для рабочего контура credentials приходят только через MCP HTTP headers:
   - `X-VM-Domain`
   - `X-VM-Api-Key`
4. Контейнеры запускаются с UID/GID хоста для корректной работы с bind mounts.

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
клиентов вроде Cursor/Claude через `url + headers`.

#### Vetmanager API client (`vetmanager_client.py`)

`VetmanagerClient` создаётся на каждый MCP request context и инкапсулирует:
- чтение credentials из текущего HTTP request;
- валидацию `domain` как subdomain;
- резолв базового host через billing API:
  `https://billing-api.vetmanager.cloud/host/{domain}`;
- allowlist-проверку резолвленного host;
- автоматическую подстановку `X-REST-API-KEY`;
- request pacing: минимум 50ms между последовательными исходящими запросами;
- retry/timeout поведение;
- нормализацию ошибок в исключения уровня приложения;
- in-memory tagged cache для GET-запросов.

#### Credential extraction (`request_credentials.py`)

Модуль извлекает `X-VM-Domain` и `X-VM-Api-Key` из текущего HTTP request.

Контракт:
- инструменты и prompts не принимают runtime credentials как аргументы;
- при отсутствии headers сервер возвращает явную безопасную ошибку;
- секреты не должны раскрываться в логах и пользовательских ошибках.

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

#### MCP prompts (`prompts.py`)

Prompts регистрируются отдельно от tools и:
- реализуют типовые workflow-сценарии для LLM;
- работают по тому же headers-only контракту;
- не принимают `domain` / `api_key`;
- не должны подсказывать передачу credentials в tool calls.

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
- `domain` и `api_key` не передаются в аргументах tools/prompts;
- `domain` и `api_key` не задаются проектным `.env` для runtime;
- `TEST_DOMAIN` / `TEST_API_KEY` допустимы только для real e2e tests;
- один экземпляр сервера обслуживает разные клиники без перезапуска.

#### Host resolution

При первом обращении внутри `VetmanagerClient`:
1. из headers читается `domain`;
2. выполняется `GET https://billing-api.vetmanager.cloud/host/{domain}`;
3. из ответа извлекается clinic-specific base URL;
4. URL проходит HTTPS и allowlist проверку;
5. результат кешируется в экземпляре клиента.

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
- отсутствие runtime credentials в репозитории;
- безопасные лимиты на list операции и суммы платежей.

### 4.4. Производительность и кеширование

- Между последовательными HTTP-запросами к Vetmanager API действует минимальный gap 50ms.
- GET-запросы кешируются in-memory.
- Кеш изолирован по `api_key_hash`, чтобы не смешивать ответы разных tenants.
- После мутаций выполняется tag invalidation по `domain:entity`.

## 5. Тестирование

Проект использует три уровня проверки:

### 5.1. Unit tests

Покрывают:
- credential extraction;
- multitenancy и security ограничения клиента;
- validation helpers;
- schema/export contracts.

### 5.2. Mock e2e / contract tests

Запускаются через `respx` и проверяют:
- маршрутизацию к billing API и Vetmanager API;
- корректность HTTP payload/query params;
- поведение агрегирующих инструментов;
- ключевые safety и cache сценарии.

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
через `url + headers`.

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
