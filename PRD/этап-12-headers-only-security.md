# PRD Этап 12: Headers-only контракт и security hardening

## Цель
Перевести MCP-сервер на строгий runtime-контракт, где credentials берутся только из HTTP headers (`X-VM-Domain`, `X-VM-Api-Key`), без параметров `domain`/`api_key` в сигнатурах инструментов. Дополнительно внедрить security-усиления и межзапросную задержку 50ms для исходящих HTTP-запросов к Vetmanager API.

## Контекст
- Этап 11 внедрил Variant A (`mcp.json` headers), но сохранил backward-compatible аргументы инструментов `domain`/`api_key`.
- Требуется намеренный breaking change: старые клиенты можно не поддерживать.
- Нужно синхронизировать контракт в коде, тестах и артефактах.

## Декомпозиция задач

### 12.1 Управленческие артефакты и контракт
- Обновить `Roadmap.md` новым этапом 12.
- Актуализировать `artifacts/prd-vetmanager-mcp-ru.md` под headers-only.
- Зафиксировать требования к security и pacing.
- Оценка: <= 80 строк.

### 12.2 Тесты (Red)
- Обновить unit/e2e тесты под новый контракт без `domain`/`api_key` в инструментах.
- Добавить проверки:
  - credentials только из headers;
  - ошибка без headers;
  - 50ms pacing между последовательными HTTP-запросами одного клиента;
  - валидация `domain`;
  - host policy (HTTPS + allowlist).
- Оценка: <= 150 строк.

### 12.3 Реализация headers-only в инструментах
- Удалить `domain`/`api_key` из сигнатур всех `tools/*.py`.
- Обновить docstrings инструментов под новый контракт.
- Оценка: <= 150 строк на подмодуль (выполняется по модулям).

### 12.4 Реализация security/pacing в `VetmanagerClient`
- Credentials только из headers запроса.
- Валидация `domain` регулярным выражением (subdomain-safe формат).
- Проверка резолвленного host: только HTTPS и allowlist доменов Vetmanager.
- Добавить 50ms wait между последовательными исходящими HTTP-запросами клиента.
- Добавить ограниченные retries на сетевые ошибки/timeout.
- Маскировать секреты в ошибках/логах.
- Оценка: <= 150 строк.

### 12.5 Документация и закрытие этапа
- Обновить `README.md` (breaking change, headers-only).
- Обновить `AssumptionLog.md` архитектурными решениями.
- Перевести задачи этапа 12 в `done` в `Roadmap.md`.
- Оценка: <= 80 строк.

## Критерии готовности
- В сигнатурах MCP-инструментов нет `domain`/`api_key`.
- Runtime credentials читаются только из `X-VM-Domain` и `X-VM-Api-Key`.
- Без заголовков инструменты возвращают понятную ошибку авторизации/конфигурации.
- Для одного инстанса клиента соблюдается минимум 50ms между последовательными исходящими HTTP-вызовами.
- Реализованы domain validation и host policy (HTTPS + allowlist).
- Тесты проходят по проектному workflow.
- `README.md`, `Roadmap.md`, `AssumptionLog.md`, `artifacts/prd-vetmanager-mcp-ru.md` синхронизированы.
