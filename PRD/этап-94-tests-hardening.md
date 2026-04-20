# Этап 94. Tests hardening — structural filter assertions + billing API coverage

## Цель

Сделать тесты менее хрупкими и закрыть недостающие billing-api error paths без широкого тестового рефакторинга.

## Контекст

Baseline findings:
- medium fragile: `tests/test_inactive_clients.py` / `test_inactive_pets.py` используют `'"ACTIVE"' in filter_param` / `'"alive"' in filter_param` substring-matches — могут ложно пройти при рассинхроне имени поля.
- medium missing_coverage: нет тестов на billing API non-200 (404/500 → HostResolutionError).

## Scope

**В scope (94):**
- Заменить substring-match filter assertions на `json.loads + структурный поиск` в `test_inactive_clients.py` и `test_inactive_pets.py`.
- Добавить 2 теста на billing-API non-200 → `HostResolutionError` в `tests/test_host_resolver.py`.

**Вне scope (→ 94b):**
- `runtime_factories` refactor (test-mode constructor vs manual private-attr injection) — wide test refactor, требует осторожной декомпозиции.
- `test_client_multitenancy` private-attr asserts replacement — зависит от runtime_factories рефактора.
- Other boundary gap tests (zero-length timesheet, last_visit_date=None, etc).

## Подзадачи

### 94.1 Structural filter assertion в test_inactive_clients

В `tests/test_inactive_clients.py` найти `assert '"status"' in filter_param` и `assert '"ACTIVE"' in filter_param`. Заменить на `json.loads(filter_param)` и структурный поиск конкретного filter item с `property="status"` и `value="ACTIVE"` и `operator="="`.

LOC: ≤20.

### 94.2 Structural filter assertion в test_inactive_pets

Аналогично для `tests/test_inactive_pets.py`: `assert '"alive"' in filter_param` → structural.

LOC: ≤15.

### 94.3 Billing API non-200 coverage

В `tests/test_host_resolver.py` (или создать если нет) добавить:
- `test_billing_api_404_raises_host_resolution_error`
- `test_billing_api_500_raises_host_resolution_error`

LOC: ≤50.

### 94.4 Run + commit

Codex — skip (tests-only, structural-equivalent replacements).

## Acceptance

- substring-match исчезает из test_inactive_clients/pets
- 2 новых billing-API error-path теста
- Full suite зелёный
