# Tech Debt Register: vetmanager-mcp

Дата: 2026-03-27 (обновлено после stages 51-55)

## P1

### TD-46-01 Разрезать `web.py` на feature modules

- Severity: высокая
- Cost: medium
- Rationale:
  `web.py` на 1453 LOC (рост с 1422) уже совмещает слишком много responsibility
  и является главным regression hotspot. Запланировано в этапе 59.
- Target split:
  - `web_routes_auth`
  - `web_routes_account`
  - `web_routes_observability`
  - `web_rendering`

### TD-46-02 Разделить orchestration и transport в `vetmanager_client.py`

- Severity: высокая
- Cost: medium
- Rationale:
  host resolution, cache policy, retries, scope enforcement и HTTP transport
  живут в одном классе.

### TD-46-03 Разделить validation и persistence в `vetmanager_connection_service.py`

- Severity: высокая
- Cost: medium
- Rationale:
  модуль одновременно отвечает за user-facing validation, persistence и upstream checks.

## P2

### TD-46-04 Отвязать audit metadata от web security helper

- Severity: средняя
- Cost: low
- Rationale:
  `auth_audit.py` зависит от `web_security.resolve_client_ip`, что связывает
  audit слой с web-specific реализацией.

### TD-46-05 Вынести common web guards и response builders

- Severity: средняя
- Cost: low
- Rationale:
  текущий повторяемый pattern login redirect / account lookup / csrf error
  держится на локальных helper blocks внутри `web.py`.

### TD-46-06 Разрезать `tests/test_e2e_mock.py`

- Severity: средняя
- Cost: medium
- Rationale:
  118 тестов в одном файле (1887 LOC, рост с 91) ухудшают навигацию
  и review cost. Запланировано в этапе 60.

## P3

### TD-46-07 Выделить shared test app/bootstrap helpers

- Severity: средняя
- Cost: low
- Rationale:
  в web-oriented tests повторяются patterns isolated DB/bootstrap.

### TD-46-08 Формализовать internal contracts для observability labels

- Severity: средняя
- Cost: low
- Rationale:
  label and event naming stability пока в основном зафиксированы tests + docs.

### TD-46-09 Сузить `tools.register_all` к declarative registry

- Severity: низкая
- Cost: low
- Rationale:
  ручной import/register sequence будет неудобен при росте числа modules.

## Quick Wins

- TD-46-04
- TD-46-05
- TD-46-07
- TD-46-08
- TD-46-09

## Long-Term Refactors

- TD-46-01
- TD-46-02
- TD-46-03
- TD-46-06

---

## Новые items (stages 51-55)

### TD-55-01 Зависимости без upper bounds в Dockerfile

- Severity: высокая
- Cost: low
- Rationale:
  `fastmcp>=2.0.0`, `httpx>=0.27.0` и др. без upper bounds — риск
  breaking changes и невоспроизводимых сборок. Запланировано в этапе 58.

### TD-55-02 CSP `style-src 'unsafe-inline'`

- Severity: средняя
- Cost: medium
- Rationale:
  inline styles ослабляют CSP. Нужно вынести стили в external CSS или
  использовать nonce. Запланировано в этапе 58.

### TD-55-03 Process-local rate limiting

- Severity: средняя
- Cost: high
- Rationale:
  Rate limiting (bearer + web) хранится in-memory и не шарится между
  workers. Для multi-instance deployment нужен Redis. Деферировано из
  этапа 54.2, отложено до реальной потребности в горизонтальном масштабировании.

### TD-55-04 Нет coverage reporting в CI

- Severity: низкая
- Cost: low
- Rationale:
  Отсутствует pytest-cov и минимальный порог покрытия. Запланировано
  в этапе 60.

## Новые items (этап 61 — ревью архитектуры)

### TD-61-01 God-object VetmanagerClient (8 ответственностей)

- Severity: критическая
- Cost: high
- Rationale:
  vetmanager_client.py совмещает HTTP, auth resolution, кеширование,
  rate limiting, host resolution, scope check, error translation,
  observability. Затрудняет тестирование и расширение.

### TD-61-02 CRUD boilerplate дублирование в tools/ (50+ функций)

- Severity: критическая
- Cost: high
- Rationale:
  12 tool-модулей независимо реализуют идентичные list/by_id/create/
  update/delete паттерны. Добавление новой сущности требует копирования
  ~100 строк boilerplate.

### TD-61-03 Криптография в ORM-моделях

- Severity: высокая
- Cost: low
- Rationale:
  storage_models.py вызывает encrypt/decrypt/hash напрямую. Модели
  должны быть dumb data structures; crypto — в сервисном слое.

### TD-61-04 Encryption key доступ без валидации

- Severity: высокая
- Cost: low
- Rationale:
  5 мест в runtime_auth.py и web.py используют os.environ.get()
  напрямую, обходя валидацию get_storage_encryption_key().

### TD-61-05 Приватная _validate_domain() экспортирована в 3 модуля

- Severity: высокая
- Cost: low
- Rationale:
  Функция с _ префиксом используется как публичная. Нужен отдельный
  модуль domain_validation.py с публичным API.

### TD-61-06 Scope checking не fail-fast

- Severity: высокая
- Cost: medium
- Rationale:
  Токен с недостаточными правами проходит bearer_auth и отклоняется
  только при выполнении запроса в vetmanager_client. Нарушение fail-fast.

### TD-61-07 Pagination loop дублируется в 3 модулях

- Severity: высокая
- Cost: low
- Rationale:
  Идентичный while/offset/totalCount цикл в client.py, invoice.py,
  medical_card.py. Нужна утилита paginate_all().
