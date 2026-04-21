# Этап 123. Contract tests rewrite + mutation unhappy-path coverage

## Контекст

Super-review 2026-04-20 показал, что часть mock/e2e тестов закрепляет **неправильный** wire-contract к Vetmanager API:
- `tests/test_e2e_mock_entities.py::test_create_pet` до сих пор постит `client_id` вместо `owner_id`;
- `test_create_admission` работает мимо MCP tool layer и закрепляет legacy payload `{pet_id, doctor_id, date}`;
- в `tests/test_e2e_mock_crud.py` многие mutation tests проверяют только `route.called`, не HTTP method / URL / body;
- unhappy-path coverage по POST/PUT/DELETE распределена неравномерно.

Из-за этого stage 122 payload fix мог бы прожить без CI-signal. Stage 123 должен превратить mutation tests в настоящий contract gate.

## Цель

Сделать mutation/mock tests чувствительными к откату field-name migrations и к ошибкам tool layer:
- outbound payload должен проверяться через `mcp.call_tool(...)`;
- invalid enum/value cases должны падать до HTTP вызова, где это ожидается;
- update/delete/create tests должны проверять не только факт вызова, но и wire contract.

## Scope

**В scope:**
- `tests/test_e2e_mock_entities.py`
- `tests/test_api_contracts_hotfix.py`
- `tests/test_e2e_mock_crud.py`

**Вне scope:**
- real API teardown/lifecycle infrastructure;
- переписывание вообще всех list/read-only tests;
- новые product fixes вне тестового слоя.

## Подзадачи

### 123.1 Rewrite broken entity create fixtures (≤2 ч)

- `test_create_pet` → через `mcp.call_tool("create_pet", ...)`, assert payload `owner_id`
- `test_create_admission` → через `mcp.call_tool("create_admission", ...)`, assert payload `patient_id/user_id/admission_date/status=save`
- response fixtures синхронизировать с актуальными полями: `admission_date`, `patient_id`

### 123.2 Invalid-status guard (≤30 мин)

- `tests/test_api_contracts_hotfix.py::test_create_admission_invalid_status_rejected`
- ожидание: `ValueError` до HTTP вызова

### 123.3 Tighten CRUD mutation assertions (≤2 ч)

- update/delete/create tool tests в `tests/test_e2e_mock_crud.py` должны проверять:
  - HTTP method
  - URL path
  - наличие/содержание body, если запрос не DELETE
- убрать голые `assert route.called` там, где можно проверить точнее

### 123.4 Mutation unhappy-path coverage (≤2 ч)

- добавить representative 4xx/5xx tests для POST/PUT/DELETE через `mcp.call_tool`
- как минимум один create, один update, один delete путь
- цель: tool layer реально пробрасывает ошибки, а не только happy path

### 123.5 Regression run + audit (≤2 ч)

- targeted pytest на три файла
- полный `docker compose --profile test run --rm test`
- audit: tests действительно падают при откате 77.4 / 86 / 122 migrations

## Верификация

- targeted tests зелёные
- полный test suite зелёный
- `tests/test_e2e_mock_entities.py` не содержит raw-POST bypass для `create_pet` / `create_admission`

## Риски

- При tightening assertions могут всплыть старые shape drift'ы в unrelated fixtures; не расширять scope без необходимости.
- Если invalid-status сейчас не валидируется в tool layer, stage потребует минимальную product change в `tools/admission.py`; это допустимо, потому что тест фиксирует желаемый runtime guard.
