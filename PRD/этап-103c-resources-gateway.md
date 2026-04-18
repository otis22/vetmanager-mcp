# Этап 103c — `resources/<entity>.py` gateway layer

## Цель

Выделить entity-specific логику сборки aggregate-профилей из `tools/` в отдельный `resources/` package. Tools становятся тонкой обёрткой: парсинг аргументов + делегирование в resource + декорирование через `@mcp.tool`. Resource владеет знанием VM-полей (`patient_id`, `owner_id`, `admission_date`) и композицией секций.

## Scope (focused subset)

Текущее состояние: `tools/client.py::_get_client_profile_impl` (70 LOC) и `tools/pet.py::_get_pet_profile_impl` (65 LOC) содержат inline JSON filter-building, список секций для `gather_sections`, и response-unwrapping. Это entity-specific logic, но живёт в tool registration function'ах — тяжело тестировать в изоляции.

Стадия 103c (focused):
1. Создать `resources/__init__.py` + `resources/client_profile.py` + `resources/pet_profile.py`.
2. Каждый модуль экспортирует одну async function `fetch(<id>: int) -> dict` которая возвращает полностью собранный профиль (со всеми `partial`/`section_errors` полями).
3. `tools/client.py::_get_client_profile_impl` и `tools/pet.py::_get_pet_profile_impl` становятся однострочными делегаторами на `client_profile.fetch(client_id)` / `pet_profile.fetch(pet_id)`.

**Non-scope:** 
- Полный Resource class abstraction (CRUD methods) — не добавляет ценности для тестируемости текущих CRUD tools.
- Мигрировать остальные tools (invoice/admission/good/user/etc.) — их CRUD и так живёт в `crud_helpers`.
- Менять signatures tool-функций.

## Критические BC-факты

1. `tools.admission.ACTIVE_ADMISSION_STATUSES` — источник истины для active-admission enum. Resource модуль должен импортировать оттуда.
2. `gather_sections` из `tools._aggregation` — уже стандартный aggregator helper. Resources используют его как-есть.
3. `VetmanagerClient` instantiation остаётся в resource (не tool) — тесты мокают `httpx` через respx, не сам класс, так что место инстанциирования не важно.
4. `service_metrics.instrument_call` wrap остаётся в tool (верхний уровень MCP-операции); resource — чистая async function без инструментации.

## Acceptance

- `resources/client_profile.py`, `resources/pet_profile.py` созданы (~60–75 LOC each).
- `tools/client.py::_get_client_profile_impl` и `tools/pet.py::_get_pet_profile_impl` сжаты до 1–3 строк делегации.
- `tools/client.py` and `tools/pet.py` больше не импортируют `_json`, `ACTIVE_ADMISSION_STATUSES`, `gather_sections` (переехали в resources).
- Все 648 тестов passed, ноль warnings.
- `scripts/lint_api_contracts.py` clean.
- Codex review: 0 critical, 0 warning после 1 итерации.

## План работы

1. **resources/client_profile.py** — вынос `_get_client_profile_impl` как `fetch(client_id)`.
2. **resources/pet_profile.py** — вынос `_get_pet_profile_impl` как `fetch(pet_id)`.
3. **tools/client.py** + **tools/pet.py** — делегация.
4. Full suite test.
5. Codex review.
6. Commit.
