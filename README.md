# vetmanager-mcp

MCP-сервер для интеграции [Vetmanager REST API](https://help.vetmanager.cloud/article/3029) с любым клиентом, поддерживающим [Model Context Protocol](https://modelcontextprotocol.io/). Позволяет управлять операциями ветеринарной клиники (клиенты, питомцы, приёмы, медкарты, счета, товары/услуги) через диалоговых AI-агентов на естественном языке.

Сервер берёт на себя аутентификацию, динамическое определение URL API (через `billing-api.vetmanager.cloud`) и форматирование данных, предоставляя набор MCP-инструментов с полной поддержкой CRUD-операций.

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

# с реальным API (devtr6)
docker compose run --rm -e TEST_DOMAIN=devtr6 -e TEST_API_KEY=<key> test
```

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

Каждый инструмент принимает `domain` и `api_key` как параметры запроса — сервер поддерживает несколько клиник одновременно без перезапуска.

| Сущность | Инструменты |
|----------|-------------|
| Client | `get_clients`, `get_client_by_id`, `create_client`, `update_client` |
| Pet | `get_pets`, `get_pet_by_id`, `create_pet` |
| Admission | `get_admissions`, `get_admission_by_id`, `create_admission` |
| MedicalCard | `get_medical_cards`, `get_medical_card_by_id`, `create_medical_card` |
| Invoice | `get_invoices`, `get_invoice_by_id`, `create_invoice` |
| Good | `get_goods`, `get_good_by_id` |
| User | `get_users`, `get_user_by_id` |

## Артефакты

| Путь | Назначение |
|------|------------|
| `artifacts/prd-vetmanager-mcp-ru.md` | Требования к продукту (PRD): видение, цели, пользовательские персоны, функциональные и нефункциональные требования |
| `artifacts/technical-requirements-vetmanager-mcp-ru.md` | Технические требования: архитектура, стек, структура проекта, детали реализации |
| `artifacts/api_entity_reference-ru.md` | Справочник по сущностям Vetmanager API (Client, Pet, Admission, MedicalCard, Invoice, Good, User и др.) |
| `artifacts/vetmanager_openapi_v6.json` | Спецификация OpenAPI v6 для Vetmanager REST API |
| `artifacts/vetmanager_postman_collection.json` | Коллекция Postman для ручного тестирования Vetmanager API |
