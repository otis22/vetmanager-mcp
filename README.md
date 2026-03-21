# vetmanager-mcp

MCP-сервер для интеграции [Vetmanager REST API](https://help.vetmanager.cloud/article/3029) с любым клиентом, поддерживающим [Model Context Protocol](https://modelcontextprotocol.io/). Позволяет управлять операциями ветеринарной клиники через диалоговых AI-агентов на естественном языке.

Сервер берёт на себя bearer-аутентификацию сервиса, хранение Vetmanager credentials на уровне service account, динамическое определение URL API (через `billing-api.vetmanager.cloud`) и форматирование данных. Runtime-контур теперь **bearer-only**: MCP-клиент передаёт только `Authorization: Bearer <service_token>`, а активное Vetmanager-подключение определяется через account context.

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
- `PORT`, `MCP_PATH`, `LOG_LEVEL` — стандартные настройки MCP HTTP runtime.

Запуск тестов:

```bash
# unit + mock (без реального API)
docker compose run --rm test

# с реальным API
docker compose run --rm -e TEST_DOMAIN=<домен> -e TEST_API_KEY=<ключ> test
```

## Bearer-only runtime

Рабочий MCP runtime больше не принимает `X-VM-Domain` и `X-VM-Api-Key` в HTTP-заголовках. Все tools и prompts работают только через `Authorization: Bearer <service_token>`.

Bearer-токен привязан к account сервиса:

- `service_bearer_token` идентифицирует account;
- account хранит ровно одно активное `vetmanager_connection`;
- активное connection сейчас поддерживает auth mode `domain + rest_api_key`;
- домен и Vetmanager API key хранятся в storage-слое и не передаются в MCP tool arguments.

### Текущий статус provisioning

Пользовательский web-кабинет для регистрации account, настройки Vetmanager integration и выпуска Bearer-токенов ещё не реализован. Этот self-service контур запланирован на этап 24.

На текущем этапе в репозитории уже есть:

- storage foundation и миграции для `accounts`, `vetmanager_connections`, `service_bearer_tokens`;
- шифрование Vetmanager credentials;
- hash-only хранение bearer-токенов;
- сервис сохранения Vetmanager connection `domain + rest_api_key`.

То есть runtime-контракт уже bearer-only, но выпуск account/token пока считается internal/dev provisioning path.

## Подключение Cursor

### Шаг 1 — запустить сервер

```bash
cp .env.example .env          # задайте UID/GID и LOG_LEVEL при необходимости
docker compose up -d mcp
```

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
| e2e real tests | `TEST_DOMAIN` / `TEST_API_KEY` в `.env` или CI secrets |
| Проектный `.env` (runtime) | используется только для infra-конфига (`DATABASE_URL`, `STORAGE_ENCRYPTION_KEY`, transport settings) |

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

Добавить API-ключ для реальных тестов: **Settings → Secrets and variables → Actions → New repository secret**, имя: `VETMANAGER_TEST_API_KEY`.

## Артефакты

| Путь | Назначение |
|------|------------|
| `artifacts/prd-vetmanager-mcp-ru.md` | Требования к продукту: видение, цели, персоны, функциональные и нефункциональные требования |
| `artifacts/technical-requirements-vetmanager-mcp-ru.md` | Технические требования: архитектура, стек, структура проекта |
| `artifacts/api_entity_reference-ru.md` | Справочник по сущностям Vetmanager API (35 сущностей) |
| `artifacts/vetmanager_openapi_v6.json` | Спецификация OpenAPI v6 для Vetmanager REST API |
| `artifacts/vetmanager_postman_collection.json` | Коллекция Postman для ручного тестирования |
