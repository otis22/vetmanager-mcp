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
