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
