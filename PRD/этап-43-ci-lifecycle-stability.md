# PRD: Этап 43. Чистый CI и стабилизация test/runtime lifecycle

## Контекст

Функциональный roadmap закрыт, но default test suite всё ещё даёт warning-шум.
Первый подэтап — убрать `aiosqlite` thread/event-loop warnings, которые
появляются из-за неполного lifecycle custom async engines в тестах.

## Цель этапа 43

Сделать test/runtime lifecycle предсказуемым и подготовить почву для более
жёсткого quality gate в CI.

## Цель 43.1

Найти и устранить источник `aiosqlite` warnings вида `Event loop is closed`
в тестовом suite без подавления warning-фильтрами.

## Решение

- Не маскировать warnings через `filterwarnings`.
- Исправить lifecycle custom SQLite async engines, создаваемых тестами.
- Вынести reusable helper для session factory, который гарантированно
  делает `engine.dispose()` в teardown/finally.

## Декомпозиция

### 43.1.1 Артефакты
- Создать PRD этапа 43.
- Перевести `43.1` в `in_progress`.

### 43.1.2 Reproduction
- Подтвердить источник warning через текущие async test helpers.

### 43.1.3 Fix
- Добавить disposable session-factory helper для async tests.
- Перевести проблемные test modules на новый helper.

### 43.1.4 Validation
- Прогнать целевой subset.
- Прогнать полный suite.
- Обновить `AssumptionLog.md`.

## Критерии готовности

- `aiosqlite` warnings больше не возникают в default suite.
- Решение не основано на ignore/filter policy.
- Изменение остаётся локальным для test infrastructure и не ломает runtime.

## Цель 43.2

Устранить `DeprecationWarning` от `uvicorn/websockets` в live browser harness
без подавления warning-фильтрами и без изменения runtime-контракта приложения.

## Решение 43.2

- Не добавлять глобальные ignore/filter rules для `DeprecationWarning`.
- Проверить, действительно ли live browser harness использует только HTTP.
- Если websocket transport не нужен, отключить websocket protocol в test-only
  `uvicorn.Config`, чтобы не импортировался legacy `websockets` stack.

## Декомпозиция 43.2

### 43.2.1 Reproduction
- Подтвердить, что warning приходит из test-only live HTTP server.

### 43.2.2 Fix
- Изменить конфигурацию test-only uvicorn server так, чтобы browser harness
  поднимался только как HTTP endpoint без websocket protocol.

### 43.2.3 Validation
- Прогнать browser/live subset с `DeprecationWarning` как ошибкой.
- Прогнать полный suite.
- Обновить `AssumptionLog.md`.

## Критерии готовности 43.2

- Browser/live tests проходят без `uvicorn/websockets` deprecation warnings.
- Решение ограничено test infrastructure.
- Полный suite проходит без неожиданных warning'ов от browser harness.

## Цель 43.3

Зафиксировать явную warning policy для test/CI contour: какие warnings считаются
допустимыми, какие блокируют CI, и какие механизмы suppression разрешены.

## Решение 43.3

- Сделать policy machine-readable, чтобы следующие этапы могли использовать её
  как источник истины.
- Зафиксировать нулевую tolerance для warnings в default suite.
- Явно запретить глобальные `ignore`/`default` фильтры в `pytest.ini`.
- Разрешить только scoped suppression, если она когда-либо понадобится:
  per-test/per-module с явной причиной и отдельной roadmap-задачей.

## Декомпозиция 43.3

### 43.3.1 Policy contract
- Добавить модуль с явной warning policy для default и opt-in suites.

### 43.3.2 Guardrails
- Добавить тесты, которые проверяют:
  - default suite требует zero warnings;
  - блокирующие категории определены явно;
  - в `pytest.ini` нет глобальных filterwarnings-ignore правил.

### 43.3.3 Validation
- Прогнать policy tests.
- Прогнать полный suite.
- Обновить `AssumptionLog.md`.

## Критерии готовности 43.3

- В репозитории есть явный source of truth для warning policy.
- Policy отделяет default CI-blocking contour от opt-in contour.
- Добавлены guardrails против тихого появления глобальных warning-ignore правил.

## Цель 43.4

Включить для default suite реальный fail-on-unexpected-warnings режим, который
использует policy из `43.3` и не опирается на ручные договорённости.

## Решение 43.4

- Добавить отдельный launcher для default suite.
- Launcher должен запускать pytest с `-W error::...` по blocking categories из
  warning policy.
- `docker compose run --rm test` должен перейти на этот launcher.

## Декомпозиция 43.4

### 43.4.1 Launcher
- Добавить script/entrypoint для default suite с warning-as-error flags.

### 43.4.2 Integration
- Подключить launcher в `docker-compose.yml` для profile `test`.

### 43.4.3 Validation
- Прогнать launcher отдельно.
- Прогнать полный suite через обычную compose-команду.
- Обновить `AssumptionLog.md`.

## Критерии готовности 43.4

- `docker compose run --rm test` падает на unexpected warnings.
- Конфигурация опирается на warning policy, а не на разрозненный inline shell.
- Default suite по-прежнему проходит зелёным на текущем состоянии репозитория.
