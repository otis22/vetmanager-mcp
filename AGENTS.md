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

- ShellCheck и синтаксис Bash (обязательны перед commit при изменении `scripts/*.sh`): `find scripts/ -name '*.sh' -type f -print0 | xargs -0 docker run --rm -v "$PWD:/mnt" -w /mnt koalaman/shellcheck:v0.9.0 --severity=warning` и `find scripts/ -name '*.sh' -type f -print0 | while IFS= read -r -d '' f; do bash -n "$f"; done`. Первая команда сама скачивает официальный образ при чистой Docker-сессии и фиксирована на версии CI.
- Unit + mock e2e: `docker compose --profile test run --rm test`
- Real API e2e (только если в `.env` есть test `TEST_DOMAIN` и `TEST_API_KEY`; секреты не печатать): `docker compose --env-file .env --profile test run --rm test python scripts/run_opt_in_real_test_suite.py`
- CI: `.github/workflows/test.yml` (unit + mock); `test-real.yml` — ручной запуск с секретом.

Задача не считается завершённой без прохождения проверок и записи в AssumptionLog.

Дополнение к workflow:
- Перед `commit`/`push` агент обязан сделать аудит внесённых изменений.
- Если аудит потребовал рефакторинга, после него обязателен новый полный прогон тестов и проверок.
- Команда попадает в процессную документацию только после запуска в точно записанном виде: перед commit агент копирует её из документации и проверяет реальный exit code. Эквивалентная команда не заменяет эту проверку.
- Ревью сторонней моделью: Claude-агент проверяется Codex `gpt-5.5`, Codex-агент проверяется Claude Opus.
- Бюджет сторонней модели: 2 валидных запуска на PRD-review и 2 валидных запуска на code/diff review; валидным является только запуск с разбираемым вердиктом — findings или явный пустой список. `gpt-5.3-codex-spark` как обычный scout/subagent безлимитен и не расходует бюджет. Для Spark-review перед конкретным review gate действует отдельный лимит: максимум 3 запуска.
- Перед каждым PRD/code review агент делает Spark-review `gpt-5.3-codex-spark`, затем более сильное ревью. `gpt-5.3-spark` — неправильное/неполное имя модели; использовать только `gpt-5.3-codex-spark`.
- Spark findings являются candidate-only: агент обязан проверить адекватность и принимать только важные, проверяемые замечания; speculative/low-impact/неподтверждённые замечания отклоняются.
- Spark-review prompt должен быть узким: указать объект ревью (PRD, staged/uncommitted diff, committed diff), severity, формат ответа и запрет на правки.
- Правильный вызов Spark-review из Codex runtime: `timeout 1200 codex exec -m gpt-5.3-codex-spark -s read-only -C "$PWD" -`. Если read-only падает до чтения файлов из-за sandbox/runtime ошибки (`bwrap`, user namespace и т.п.), остановить зависший запуск и один раз повторить ту же модель с `-s danger-full-access` и review-only prompt: `Review only. Do not edit files. Do not run write commands.` Fallback на другую модель разрешён только при явной model/provider failure, не при sandbox/runtime failure. Итог Spark-review (`[]` или принятые/отклонённые findings) фиксируется в AssumptionLog.
- Claude Opus review из Codex runtime: real shell timeout должен быть минимум в 2 раза больше prompt deadline; default `timeout 1200`, в prompt писать `Finish this review within 600 seconds`, реальный timeout Claude не сообщать. Для inline diff/context отключать tools/MCP (`--strict-mcp-config --mcp-config '{"mcpServers":{}}' --tools ""`), запрещать правки/commands, требовать structured JSON findings через `--output-format json` + schema и писать `Think briefly, then return JSON matching the schema immediately`. Успех: JSON-конверт разобран, `is_error=false`, непустое поле `.result` разбирается по required schema. Валидатор вызывать напрямую как исполняемый `scripts/validate_review_result.py`, не через имя интерпретатора; CI проверяет этот вызов. Сбой: конверт не JSON, `is_error=true`, `.result` пусто/не разбирается/не соответствует schema либо provider/model error. `stop_reason` не участвует: при `--json-schema` structured result штатно доставляется tool call. Infrastructure failure не расходует слот и фиксируется отдельной строкой в `AssumptionLog` как `N/3`; максимум три таких попытки на strong review gate, затем `blocked` и push запрещён. Только запуск с разбираемым verdict расходует слот бюджета.

### Evidence Claude review

Каждую попытку Claude strong review запускать через
`scripts/run_claude_review.sh (--range <range> | --file <review-file>) --attempt <N/3>`.
Для committed/uncommitted diff использовать `--range`; для PRD, Architecture
Critique и другого file-object review — `--file`. Runner независимо
от exit сохраняет вне working copy raw envelope, stderr, prompt, schema и
metadata в `${XDG_DATA_HOME:-~/.local/share}/vetmanager-mcp-review-evidence`
(или `--evidence-dir`). В
`AssumptionLog` указывать путь к `*.envelope.json` и `subtype`, `stop_reason`,
`output_tokens`, `thinking_tokens`, `len(result)`; metadata содержит
`attempt`, тип/цель review, repo, evidence dir и все параметры запуска. Запись только «без output»
запрещена. Runner валидирует сохранённый envelope и возвращает non-zero при
invalid verdict.

## Feedback triage и `known_issues`

Production feedback triage — это операционная работа, а не изменение репозитория.

Не изменять и не коммитить файлы репозитория, если единственное действие:

- чтение `agent_feedback_reports`;
- обновление production `known_issues`;
- link/resolve feedback reports;
- правки `agent_playbook_json` или `match_rules_json`;
- исследование конкретного feedback report без кода/тестов/PRD.

Для такого triage source of truth — production DB (`agent_feedback_reports`,
`known_issues`) и внешний work log супервизора.

Запрещено по умолчанию добавлять в repo только из-за triage:

- `AssumptionLog.md`;
- `README.md`;
- `artifacts/report-ai-*`;
- любые ad-hoc research artifacts.

Repo changes допустимы только если feedback породил явное product/code intent:

- code fix;
- regression test;
- Roadmap/PRD задачу на будущий fix;
- документацию, которую пользователь явно попросил добавить в репозиторий.

Перед любым commit после feedback triage агент обязан проверить
`git status --short` и `git diff --stat`. Если diff содержит только разбор
feedback или результаты правок `known_issues`, commit запрещён.
