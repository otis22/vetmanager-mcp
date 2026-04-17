# Этап 92. Auth cleanup — удалить dead public API из request_credentials

## Контекст

Baseline F10 (architecture + security, confidence 0.88): кластер auth-модулей. `request_credentials.py` помечен как dead-module — после stage 22.4 (убрана runtime-поддержка X-VM-* headers) публичная функция `get_request_credentials()` больше не вызывается. Остался только приватный helper `_get_request_headers()`, использующийся из `request_auth.py`.

## Цель

Убрать dead public API чтобы новый contributor не пытался использовать `get_request_credentials()` вместо bearer-only контракта.

## Scope

**В scope (92):**
- Удалить `get_request_credentials()` из `request_credentials.py`
- Docstring модуля актуализировать: «internal shim over fastmcp request headers, bearer-only runtime»
- Regression: full test suite зелёный

**Вне scope (→ стадия 92b в отдельной сессии):**
- Рефакторинг в `auth/` package (bearer.py/vetmanager.py/context.py)
- Split `resolve_bearer_auth_context` (170 LOC) на pipeline валидаторов
- Rate-limiter consolidation (delete `bearer_rate_limiter.py`, use `rate_limit_backend` с namespace="bearer_token")

Эти подзадачи — big refactor, high regression risk, требуют свежей сессии и отдельного PRD (92b).

## Подзадачи

### 92.1 Delete `get_request_credentials()` + update docstring

`request_credentials.py` сокращается до 15-20 строк с одной функцией `_get_request_headers()`.

LOC: ≤15.

### 92.2 Проверить, что нет callers public API

Grep `get_request_credentials` — должно остаться только в этом файле и связанных тестах, если они есть. Удалить их тоже.

### 92.3 Run tests + commit

Codex review — пропустить (удаление dead code с verified zero callers — CLAUDE.md §5.5).

## Acceptance

- `request_credentials.py` содержит только `_get_request_headers()`
- `get_request_credentials` не существует в codebase
- Full suite зелёный
