# Tech Debt Register: vetmanager-mcp

Дата: 2026-03-22

## P1

### TD-46-01 Разрезать `web.py` на feature modules

- Severity: высокая
- Cost: medium
- Rationale:
  `web.py` на 1422 LOC уже совмещает слишком много responsibility и является
  главным regression hotspot.
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
  91 тест в одном файле ухудшают навигацию и review cost.

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
