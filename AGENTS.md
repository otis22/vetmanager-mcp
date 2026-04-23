# Руководство для ИИ-агентов

Краткий указатель правил и артефактов проекта. Агент обязан следовать workflow и обращаться к артефактам при планировании и реализации.

## Cursor Rules

Правила в `.cursor/rules/` (alwaysApply или по контексту):

| Правило | Назначение |
|--------|------------|
| [.cursor/rules/agent-workflow.mdc](.cursor/rules/agent-workflow.mdc) | Workplan в Roadmap, выбор задачи, PRD gates (artifacts → PRD-review → ревью сторонней моделью → simplicity), Core Loop (тесты → Red/Green → проверки → аудит → commit → ревью сторонней моделью → push → self-attestation), AssumptionLog, справочные артефакты |

## Обязательные артефакты

| Файл / папка | Назначение |
|--------------|------------|
| [Roadmap.md](Roadmap.md) | Workplan: этапы и задачи, статусы (todo / in_progress / done / stop). Единственный источник очереди работ. |
| [AssumptionLog.md](AssumptionLog.md) | Журнал допущений, неясностей и архитектурных решений после завершения задач. |
| [PRD/](PRD/) | PRD задач с декомпозицией (подзадачи ≤ 2 ч или ≤ 150 строк). Перед реализацией — создать/прочитать PRD этапа. |

## Справочные артефакты (artifacts/)

Использовать при планировании, декомпозиции и решениях по реализации инструментов MCP:

| Файл | Когда использовать |
|------|--------------------|
| [artifacts/prd-vetmanager-mcp-ru.md](artifacts/prd-vetmanager-mcp-ru.md) | Главный PRD: видение, цели, персоны, требования — отправная точка планирования |
| [artifacts/technical-requirements-vetmanager-mcp-ru.md](artifacts/technical-requirements-vetmanager-mcp-ru.md) | Технические требования: стек, архитектура, структура проекта — перед декомпозицией |
| [artifacts/api_entity_reference-ru.md](artifacts/api_entity_reference-ru.md) | Справочник сущностей Vetmanager API (Client, Pet, Admission и др.) — при реализации инструментов MCP |
| [artifacts/vetmanager_openapi_v6.json](artifacts/vetmanager_openapi_v6.json) | Спецификация OpenAPI — источник истины для эндпоинтов и схем |
| [artifacts/vetmanager_postman_collection.json](artifacts/vetmanager_postman_collection.json) | Postman-коллекция — вспомогательный материал для запросов к API |

> Агент **не домысливает** поведение API — всё проверяется по OpenAPI или `api_entity_reference-ru.md`.

## Тесты и проверки

- Unit + mock e2e: `docker compose --profile test run --rm test`
- Real API e2e (нужны `TEST_DOMAIN`, `TEST_API_KEY`): `docker compose --profile test run --rm -e TEST_DOMAIN=<домен> -e TEST_API_KEY=<ключ> test`
- CI: `.github/workflows/test.yml` (unit + mock); `test-real.yml` — ручной запуск с секретом.

Задача не считается завершённой без прохождения проверок и записи в AssumptionLog.

Дополнение к workflow:
- Перед `commit`/`push` агент обязан сделать аудит внесённых изменений.
- Если аудит потребовал рефакторинга, после него обязателен новый полный прогон тестов и проверок.
- Ревью сторонней моделью: Claude-агент проверяется Codex `gpt-5.5`, Codex-агент проверяется Claude Opus.
- Бюджет сторонней модели: 2 запуска на PRD-review и 2 запуска на code/diff review; `gpt-5.3-codex-spark` как scout/subagent безлимитен и не расходует бюджет.
