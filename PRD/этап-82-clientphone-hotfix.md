# Этап 82. Hot-fix этапа 78: phone search через /rest/api/ClientPhone (retroactive PRD)

> **Ретроактивный PRD** — реализация этапа выполнена до документации. Записан 2026-04-17 в этапе 90 для закрытия workflow-check finding (CLAUDE.md §3 требует PRD перед реализацией). Полное описание решений и результатов — в `AssumptionLog.md` раздел «Этап 82».

## Цель

Исправить deferred issue этапа 78: `get_clients.phone` не работал для полных номеров, потому что в БД `cell_phone` хранится с форматированием (`"(918)414-02-59"`). Использовать отдельный endpoint `/rest/api/ClientPhone` с digits-only полем `clean_phone`.

## Scope

- `_resolve_client_ids_by_phone` helper с двухфазным поиском (ClientPhone → clients batch через `id IN`).
- Trailing-10 digits стратегия + fallback к full digits.
- Cap на phase 1 `totalCount > 100` → `ValueError("phone search too broad")`.
- Регистрозависимый endpoint `/rest/api/ClientPhone` (не `clientphone`).
- 7 регрессионных тестов + real API probe.

## Acceptance

- Поиск по `+7 (918)...`, `8 918...`, `7 918...`, `918414` работает корректно на devtr6.
- Composability с `status`/`email`/user-filter.
