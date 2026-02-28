# PRD Этап 11: Реализация Variant A — credentials через HTTP headers

## Цель
Реализовать поддержку credentials через HTTP headers (`X-VM-Domain`, `X-VM-Api-Key`).
Убрать env-fallback из runtime-кода. Каждый пользователь приносит свои credentials в `mcp.json`.

## Контракт Variant A

Клиентский `~/.cursor/mcp.json`:
```json
{
  "mcpServers": {
    "vetmanager": {
      "url": "http://<host>:8000/mcp",
      "headers": {
        "X-VM-Domain": "<clinic-subdomain>",
        "X-VM-Api-Key": "<rest-api-key>"
      }
    }
  }
}
```

Сервер читает `X-VM-Domain` и `X-VM-Api-Key` из входящих HTTP-заголовков и передаёт их в инструменты как дефолтные значения для параметров `domain`/`api_key`.

При явной передаче параметров в инструмент они имеют приоритет над headers.

## Задачи

### 11.1 Убрать env-fallback из `VetmanagerClient`
- Удалить чтение `VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY` из `os.environ` в `__init__`.
- При пустых `domain`/`api_key` бросать ошибку немедленно.
- Обновить error messages.
- ≤ 20 строк изменений.

### 11.2 Добавить чтение headers в `server.py`
- В `FastMCP` есть механизм `get_http_headers()` / context через `lifespan` или middleware.
- Исследовать API FastMCP для доступа к HTTP-заголовкам запроса.
- Реализовать `get_request_credentials()` → `(domain, api_key)` из headers.
- Передавать в инструменты как дефолтные значения (через контекст или context var).
- ≤ 60 строк.

### 11.3 Обновить `docker-compose.yml` и `.env.example`
- Убрать `VETMANAGER_DOMAIN`/`VETMANAGER_API_KEY` из сервиса `mcp`.
- Оставить только `TEST_DOMAIN`/`TEST_API_KEY` в `test`-сервисе.
- Обновить `.env.example` — убрать runtime credentials, добавить комментарий.
- ≤ 15 строк изменений.

### 11.4 Обновить инструкции в `server.py`
- Убрать упоминание env-fallback из `instructions`.
- Добавить описание механизма headers.
- ≤ 10 строк.

### 11.5 Написать/обновить тесты
- `test_client_multitenancy.py`: убрать тесты на env-fallback; добавить тест «пустые credentials → ошибка».
- `test_e2e_mock.py`: проверить, что tools с пустыми domain/api_key корректно возвращают ошибку.
- `test_e2e_real.py`: убедиться, что использует только `TEST_DOMAIN`/`TEST_API_KEY`.
- ≤ 40 строк изменений.

### 11.6 Обновить `README.md`
- Пример `~/.cursor/mcp.json` с `headers`.
- Раздел «Credentials policy».
- Убрать упоминание VETMANAGER_DOMAIN/VETMANAGER_API_KEY как runtime.
- ≤ 50 строк.

### 11.7 Зафиксировать в `AssumptionLog.md`
- Описать решение: Variant A, headers, без env-fallback.
- ≤ 15 строк.

## Критерии готовности
- `VetmanagerClient(domain="", api_key="")` бросает ошибку сразу (без env-lookup).
- Инструменты получают `domain`/`api_key` из HTTP headers запроса (если не переданы явно).
- `docker-compose.yml` не содержит runtime credentials.
- Все тесты проходят: `docker compose --profile test run --rm test`.
- `README.md` содержит актуальный пример `mcp.json` с headers.
