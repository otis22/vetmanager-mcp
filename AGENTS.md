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
| [artifacts/api_crud_permissions-ru.md](artifacts/api_crud_permissions-ru.md) | CRUD permissions по Vetmanager REST controllers — перед добавлением/удалением write tools |
| [artifacts/vetmanager_openapi_v6.json](artifacts/vetmanager_openapi_v6.json) | Спецификация OpenAPI — источник истины для эндпоинтов и схем |
| [artifacts/vetmanager_postman_collection.json](artifacts/vetmanager_postman_collection.json) | Postman-коллекция — вспомогательный материал для запросов к API |

> Агент **не домысливает** поведение API — всё проверяется по OpenAPI или `api_entity_reference-ru.md`.

## Тесты и проверки

- Unit + mock e2e: `docker compose --profile test run --rm test`
- Real API e2e (нужны `TEST_DOMAIN`, `TEST_API_KEY`): `docker compose --profile test run --rm -e TEST_DOMAIN=<домен> -e TEST_API_KEY=<ключ> test`
- В локальной среде real API credentials могут лежать в `.env`; не печатать секреты в ответах. Для Docker Compose `--env-file` ставится перед subcommand: `docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py`.
- CI: `.github/workflows/test.yml` (unit + mock); `test-real.yml` — ручной запуск с секретом.

Задача не считается завершённой без прохождения проверок и записи в AssumptionLog.

Дополнение к workflow:
- Перед `commit`/`push` агент обязан сделать аудит внесённых изменений.
- Если аудит потребовал рефакторинга, после него обязателен новый полный прогон тестов и проверок.
- Ревью сторонней моделью: Claude-агент проверяется Codex `gpt-5.5`, Codex-агент проверяется Claude Opus.
- Бюджет сторонней модели: 2 запуска на PRD-review и 2 запуска на code/diff review; `gpt-5.3-codex-spark` как обычный scout/subagent безлимитен и не расходует бюджет. Для Spark-review перед конкретным review gate действует отдельный лимит: максимум 3 запуска.
- Перед каждым PRD/code review агент делает Spark-review `gpt-5.3-codex-spark`, затем более сильное ревью. `gpt-5.3-spark` — неправильное/неполное имя модели; использовать только `gpt-5.3-codex-spark`.
- Spark findings являются candidate-only: агент обязан проверить адекватность и принимать только важные, проверяемые замечания; speculative/low-impact/неподтверждённые замечания отклоняются.
- Spark-review prompt должен быть узким: указать объект ревью (PRD, staged/uncommitted diff, committed diff), severity, формат ответа и запрет на правки.
- Правильный вызов Spark-review из Codex runtime: `timeout 1200 codex exec -m gpt-5.3-codex-spark -s read-only -C "$PWD" -`. Если read-only падает до чтения файлов из-за sandbox/runtime ошибки (`bwrap`, user namespace и т.п.), остановить зависший запуск и один раз повторить ту же модель с `-s danger-full-access` и review-only prompt: `Review only. Do not edit files. Do not run write commands.` Fallback на другую модель разрешён только при явной model/provider failure, не при sandbox/runtime failure. Итог Spark-review (`[]` или принятые/отклонённые findings) фиксируется в AssumptionLog.
