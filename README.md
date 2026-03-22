# vetmanager-mcp

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
- `PORT`, `MCP_PATH`, `LOG_LEVEL` — стандартные настройки MCP HTTP runtime.

Запуск тестов:

```bash
# unit + mock (без реального API)
docker compose run --rm test

# с реальным API по api_key flow
docker compose run --rm -e TEST_DOMAIN=<домен> -e TEST_API_KEY=<ключ> test

# с direct real smoke для уже выданного user-token
docker compose run --rm \
  -e TEST_DOMAIN=<домен> \
  -e TEST_USER_TOKEN=<user_token> \
  test

# с real smoke для login/password -> user token exchange
docker compose run --rm \
  -e TEST_DOMAIN=<домен> \
  -e TEST_USER_TOKEN_BASE_URL=<https://clinic.vetmanager2.ru> \
  -e TEST_USER_LOGIN=<login> \
  -e TEST_USER_PASSWORD=<password> \
  test
```

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
- `/register` и `/login` защищены process-local rate limiting от brute-force / abuse;
- HTML responses отдают baseline security headers: `CSP`, `X-Frame-Options`, `Referrer-Policy`, `X-Content-Type-Options`;
- кабинет показывает health активной integration и статус `reauth_required`, если сохранённый user token больше не проходит валидацию;
- доступен выпуск Bearer-токенов с именем и сроком действия;
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
- rate limiting для `/register` и `/login`;
- baseline security headers для HTML-ответов web UI;
- web-экран сохранения active Vetmanager integration;
- web-выпуск Bearer-токенов с one-time показом raw значения;
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

- Текущий web rate limiting process-local; для multi-instance production нужен
  shared store или edge enforcement.
- Текущий CSRF/session hardening рассчитан на single-instance deployment с
  общим `WEB_SESSION_SECRET`; при горизонтальном масштабировании нужен единый
  secret и согласованный deployment policy.
- Для production рекомендуется:
  - явный `WEB_SESSION_SECRET`;
  - явный `STORAGE_ENCRYPTION_KEY`;
  - `WEB_ENABLE_HSTS=1` за HTTPS reverse proxy;
  - внешний rate limit на `/register` и `/login`.

### Тест подключения

После запуска сервера и настройки `mcp.json` в чате Cursor попросите:

> «Покажи список клиентов клиники» — инструмент `get_clients` вызовется с bearer-derived account context.

## Деплой на сервер

Предусловие: `ssh-copy-id user@host` выполнен.

Прод-хост проекта: `342915.simplecloud.ru`.

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
./scripts/sync_and_deploy_server.sh root@212.193.59.219 /opt/vetmanager-mcp
```

Скрипт:
- синхронизирует проект через `rsync` (без `.git`, `.env`, служебных директорий);
- запускает `deploy_server.sh` с `SKIP_GIT_PULL=1`;
- выполняет те же smoke-check и TLS-check, что обычный deploy.

### Полностью автоматический деплой после push в main

Добавлен workflow: `.github/workflows/deploy-prod.yml`.

Он срабатывает после успешного workflow `Tests` для ветки `main` и делает:
- `rsync` кода на прод-сервер;
- запуск `deploy_server.sh` в режиме `SKIP_GIT_PULL=1`.

Нужные GitHub Secrets:
- `PROD_SSH_TARGET` (пример: `root@212.193.59.219`)
- `PROD_SSH_PRIVATE_KEY` (приватный ключ для SSH)
- `PROD_REMOTE_DIR` (опционально, по умолчанию `/opt/vetmanager-mcp`)
- `PROD_SSL_DOMAIN` (опционально, по умолчанию `342915.simplecloud.ru`)
- `PROD_CERTBOT_EMAIL` (опционально, email для certbot)

### TLS (Let's Encrypt) и автообновление

`init_server.sh` настраивает `nginx` reverse proxy, а `deploy_server.sh` автоматически вызывает проверку сертификата:
- если сертификата нет — будет первичный выпуск;
- если до истечения осталось меньше 30 дней — будет выполнено продление;
- после обновления сертификата `nginx` перезагружается автоматически.

По умолчанию используется домен `342915.simplecloud.ru`. При необходимости можно переопределить:

```bash
SSL_DOMAIN=342915.simplecloud.ru CERTBOT_EMAIL=ops@example.com \
./scripts/init_server.sh root@212.193.59.219

SSL_DOMAIN=342915.simplecloud.ru CERTBOT_EMAIL=ops@example.com \
./scripts/deploy_server.sh root@212.193.59.219
```

Обязательные внешние условия:
- DNS A-record `342915.simplecloud.ru` должен указывать на IP сервера;
- на сервере/в облачном firewall должны быть открыты порты `80/tcp` и `443/tcp`.

### Прод-конфиг Cursor MCP (локально, не в репозиторий)

Добавьте отдельный сервер в локальный `~/.cursor/mcp.json`.

**Только прод:**

```json
{
  "mcpServers": {
    "vetmanager-prod": {
      "url": "https://342915.simplecloud.ru/mcp",
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
      "url": "https://342915.simplecloud.ru/mcp",
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
- Ключ кеша: `METHOD + canonical_full_url_with_sorted_query + api_key_hash`.
- `api_key_hash` — отпечаток (`sha256`) API-ключа, чтобы изолировать кеш между разными ключами доступа.
- Кеш-tag: `domain:entity`, где `entity` берётся из пути `/rest/api/<entity>/...`.
- После успешного `POST`/`PUT`/`DELETE` кеш для соответствующего тега `domain:entity` инвалидируется.
- Ограничение подхода: кеш живёт только в памяти процесса и полностью сбрасывается при рестарте сервера.

**75 инструментов** по 12 группам сущностей:

| Группа | Инструменты |
|--------|-------------|
| Client | `get_clients`, `get_client_by_id`, `create_client`, `update_client` |
| Pet | `get_pets`, `get_pet_by_id`, `create_pet`, `update_pet` |
| Admission | `get_admissions`, `get_admission_by_id`, `create_admission`, `update_admission` |
| MedicalCard | `get_medical_cards`, `get_medical_card_by_id`, `create_medical_card`, `update_medical_card` |
| Invoice | `get_invoices`, `get_invoice_by_id`, `create_invoice` |
| InvoiceDocument | `get_invoice_documents`, `get_invoice_document_by_id`, `add_invoice_document` |
| Good | `get_goods`, `get_good_by_id`, `get_good_groups`, `get_good_group_by_id`, `get_good_sale_params`, `get_good_sale_param_by_id` |
| User | `get_users`, `get_user_by_id`, `get_roles`, `get_role_by_id`, `get_user_positions`, `get_user_position_by_id` |
| Finance | `get_payments`, `get_payment_by_id`, `create_payment`, `get_cassas`, `get_cassa_by_id`, `get_cassa_closes`, `get_cassa_close_by_id`, `get_closing_of_invoices`, `get_closing_of_invoice_by_id` |
| Warehouse | `get_party_accounts`, `get_party_account_by_id`, `get_party_account_docs`, `get_party_account_doc_by_id`, `get_store_documents`, `get_store_document_by_id`, `get_suppliers`, `get_supplier_by_id` |
| Clinical | `get_hospitalizations`, `get_hospitalization_by_id`, `create_hospitalization`, `get_hospital_blocks`, `get_hospital_block_by_id`, `get_diagnoses` |
| Reference | `get_breeds`, `get_breed_by_id`, `get_pet_types`, `get_pet_type_by_id`, `get_cities`, `get_city_by_id`, `get_city_types`, `get_streets`, `get_street_by_id`, `get_units`, `get_unit_by_id`, `get_combo_manual_names`, `get_combo_manual_name_by_id`, `get_combo_manual_items`, `get_combo_manual_item_by_id` |
| Operations | `get_clinics`, `get_clinic_by_id`, `get_timesheets`, `get_timesheet_by_id`, `get_properties`, `get_anonymous_clients` |

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

## CI/CD

| Воркфлоу | Триггер | Что тестирует |
|----------|---------|---------------|
| `test.yml` | push / pull request → main | unit + mock e2e (без реального API) |
| `test-real.yml` | вручную (`workflow_dispatch`) | real API e2e (требует секрет `VETMANAGER_TEST_API_KEY`) |

Добавить secrets для real tests:
- `VETMANAGER_TEST_API_KEY`
- опционально `VETMANAGER_TEST_USER_TOKEN`
- либо `VETMANAGER_TEST_USER_LOGIN` и `VETMANAGER_TEST_USER_PASSWORD`

## Артефакты

| Путь | Назначение |
|------|------------|
| `artifacts/prd-vetmanager-mcp-ru.md` | Требования к продукту: видение, цели, персоны, функциональные и нефункциональные требования |
| `artifacts/technical-requirements-vetmanager-mcp-ru.md` | Технические требования: архитектура, стек, структура проекта |
| `artifacts/api_entity_reference-ru.md` | Справочник по сущностям Vetmanager API (35 сущностей) |
| `artifacts/vetmanager_openapi_v6.json` | Спецификация OpenAPI v6 для Vetmanager REST API |
| `artifacts/vetmanager_postman_collection.json` | Коллекция Postman для ручного тестирования |
