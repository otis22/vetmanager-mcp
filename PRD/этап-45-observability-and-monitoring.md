# PRD: Этап 45. Observability, мониторинг и error telemetry

## Контекст

После завершения этапа 44 сервис получил более строгий security baseline, но
observability-контур всё ещё минимален: фактически в проекте есть только общий
`logging.basicConfig(...)` и единичные текстовые сообщения.

Для следующих шагов нужны:
- предсказуемый logging contract;
- единый формат событий;
- база для correlation id, health endpoints, metrics и error telemetry.

## Цель этапа 45

Сделать сервис наблюдаемым в эксплуатации и упростить расследование инцидентов
через structured logs, correlation id, health probes, metrics и runbook.

## Цель 45.1

Ввести structured logging contract как базовый слой observability.

## Решение 45.1

- Вынести logging setup в отдельный модуль.
- Зафиксировать два поддерживаемых формата:
  - `text` по умолчанию;
  - `json` как structured output для ingestion/aggregation.
- Обеспечить единые core fields:
  - `timestamp`
  - `level`
  - `logger`
  - `message`
- Поддержать `extra` fields в обоих форматах.

## Декомпозиция 45.1

### 45.1.1 Logging module
- Создать отдельный модуль `structured_logging.py`.
- Убрать прямой `basicConfig` из `server.py`.

### 45.1.2 Formatter contract
- Добавить JSON formatter и text formatter.
- Зафиксировать policy для неизвестного `LOG_FORMAT`.

### 45.1.3 Regression coverage
- Добавить tests на:
  - default format;
  - reject unknown format;
  - stable JSON core fields;
  - text rendering с `extra`.

### 45.1.4 Validation
- Прогнать целевые logging tests.
- Прогнать обязательный default contour.

## Критерии готовности 45.1

- В проекте есть отдельный structured logging module.
- `server.py` использует его как единственный logging entry point.
- Формат событий детерминирован и покрыт тестами.
