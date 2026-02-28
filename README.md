# vetmanager-mcp

MCP-сервер для интеграции [Vetmanager REST API](https://help.vetmanager.cloud/article/3029) с любым клиентом, поддерживающим [Model Context Protocol](https://modelcontextprotocol.io/). Позволяет управлять операциями ветеринарной клиники через диалоговых AI-агентов на естественном языке.

Сервер берёт на себя аутентификацию, динамическое определение URL API (через `billing-api.vetmanager.cloud`) и форматирование данных. Поддерживает **мультитенантность** — `domain` и `api_key` передаются в каждом MCP HTTP-запросе через заголовки, один экземпляр сервера обслуживает любое количество клиник без перезапуска.

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

Запуск тестов:

```bash
# unit + mock (без реального API)
docker compose run --rm test

# с реальным API
docker compose run --rm -e TEST_DOMAIN=<домен> -e TEST_API_KEY=<ключ> test
```

## Подключение Cursor (Variant A: credentials via headers)

Сервер не хранит runtime credentials. Каждый пользователь указывает свои `domain` и `api_key` в `~/.cursor/mcp.json` через блок `headers`.

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
        "X-VM-Domain": "myclinic",
        "X-VM-Api-Key": "your-rest-api-key"
      }
    }
  }
}
```

- `X-VM-Domain` — субдомен клиники (e.g. `myclinic` → `myclinic.vetmanager2.ru`).
- `X-VM-Api-Key` — REST API ключ из **Vetmanager → Настройки → Интеграция → Rest API**.

### Политика credentials

| Контекст | Где берутся credentials |
|----------|------------------------|
| Cursor / Claude | `~/.cursor/mcp.json` → `headers` |
| Явный аргумент инструмента | не поддерживается (headers-only контракт) |
| e2e real tests | `TEST_DOMAIN` / `TEST_API_KEY` в `.env` или CI secrets |
| Проектный `.env` (runtime) | **не используется** — runtime credentials в репозитории не хранятся |

### Тест подключения

После запуска сервера и настройки `mcp.json` в чате Cursor попросите:

> «Покажи список клиентов клиники» — инструмент `get_clients` вызовется с credentials из headers.

## Деплой на сервер

Предусловие: `ssh-copy-id user@host` выполнен.

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

## MCP-инструменты

Инструменты работают по headers-only контракту: runtime credentials берутся только из HTTP-заголовков `X-VM-Domain` / `X-VM-Api-Key` (mcp.json). Параметры `limit` (1–100) и `offset` (0–10 000) защищены от случайных массовых выборок.

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
