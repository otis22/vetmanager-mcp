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

## Цель 45.2

Добавить стабильные request/correlation id для web и MCP запросов как базу для
трассировки логов и последующих telemetry hooks.

## Решение 45.2

- Ввести общий `request_context.py`.
- Генерировать `request_id`, если клиент его не передал.
- Вычислять `correlation_id` как:
  - `X-Correlation-ID`, если он есть;
  - иначе `X-Request-ID`;
  - иначе сгенерированный `request_id`.
- Добавить эти поля:
  - в web response headers;
  - в log records через logging filter, который читает текущий FastMCP request.

## Критерии готовности 45.2

- Web responses содержат `X-Request-ID` и `X-Correlation-ID`.
- Лог-записи получают `request_id`/`correlation_id` при наличии HTTP request context.
- Поведение покрыто tests на request-context helper и logging filter.

## Цель 45.3

Разделить runtime, audit и security log events на уровне явной logger taxonomy,
а не только через произвольные `logger.name` и текст сообщений.

## Решение 45.3

- Ввести category-aware logging adapters для:
  - `runtime`
  - `audit`
  - `security`
- Добавить `event_category` и `event_name` в ключевые emission points.
- Привязать к этой таксономии:
  - runtime host resolution;
  - audit log append;
  - security events CSRF/rate-limit.

## Критерии готовности 45.3

- В проекте есть явная logger taxonomy для runtime/audit/security.
- Ключевые emission points используют её вместо неструктурированного logger split.
- Поведение покрыто tests на category contract.

## Цель 45.4

Добавить минимальные health/readiness probes для orchestration и внешнего
мониторинга, не завязывая их на HTML UI.

## Решение 45.4

- Ввести два JSON endpoint:
  - `GET /healthz` для process liveness;
  - `GET /readyz` для runtime readiness.
- Возвращать стабильный JSON contract c базовыми полями сервиса и probe status.
- Для readiness проверять доступность storage через `SELECT 1`.
- Добавить в probe responses request-context headers для трассировки.

## Критерии готовности 45.4

- `GET /healthz` отвечает `200` и не зависит от внешних upstream.
- `GET /readyz` отвечает `200`, когда storage доступен, и `503`, когда нет.
- Probe contract покрыт tests для happy-path и failure-path.

## Цель 45.5

Добавить базовые process-local service metrics, чтобы уже на уровне runtime были
видны latency/error rate, auth failures и upstream failures.

## Решение 45.5

- Ввести отдельный registry module для counters и latency aggregates.
- Считать HTTP request totals и latency для web routes.
- Отдельно считать auth failures по source/reason.
- Отдельно считать upstream failures для billing/API interaction paths.
- Сделать snapshot API, который затем можно напрямую экспортировать в 45.6.

## Критерии готовности 45.5

- В коде есть единый metrics registry без внешнего backend.
- Web routes обновляют counters/latency автоматически.
- Auth и upstream failure paths инкрементируют отдельные counters.
- Поведение покрыто tests на registry и реальные emission points.

## Цель 45.6

Подготовить прямой экспорт service metrics в формате, который можно scrape'ить
Prometheus-совместимым агентом без дополнительного adapter слоя.

## Решение 45.6

- Реализовать text exposition endpoint `/metrics`.
- Сериализовать registry в Prometheus-compatible plaintext format.
- Для latency отдать `count/sum/max` набор с явными labels.
- Сохранить scrape endpoint независимым от HTML UI.

## Критерии готовности 45.6

- В проекте есть Prometheus-compatible exporter поверх текущего registry.
- `/metrics` отвечает scrape-friendly plaintext response.
- Формат и endpoint покрыты tests.

## Цель 45.7

Добавить opt-in integration с внешней error tracking системой, чтобы
production runtime мог отправлять unhandled exceptions и error context за
пределы локальных логов.

## Решение 45.7

- Выбрать один конкретный backend: Sentry как стандартный Python/ASGI вариант.
- Инициализировать его только при наличии DSN.
- Подключить ASGI/Starlette integration на раннем этапе server bootstrap.
- Добавить sanitize hook для редактирования чувствительных headers перед отправкой.

## Критерии готовности 45.7

- Error tracking backend не активен без явного DSN.
- При наличии DSN backend инициализируется с предсказуемым config contract.
- Sensitive headers не уходят в event payload.
- Поведение покрыто tests.
