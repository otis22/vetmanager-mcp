# Этап 125. Perf N+1 + free-slot correctness

## Контекст

Super-review 2026-04-20 зафиксировал три связанных класса проблем:

1. `tools/pet.py::get_inactive_pets` всё ещё масштабируется как client-by-client scan:
   - pets ищутся по одному клиенту;
   - invoice/medcard fallback проверяется per client;
   - при большой базе это даёт N+1 / serial latency.
2. `tools/schedule.py::get_doctor_free_slots` fetch'ит `timesheet` и `admission` последовательно, а busy intervals без `clinic_id` делятся глобально на врача, из-за чего admission в clinic A может скрыть слот в clinic B.
3. `tools/crud_helpers.py::paginate_all` читает `totalCount` на каждой странице и возвращает его из последней страницы, что оставляет TOCTOU drift и не закрепляет boundary semantics 100/101.

Дополнительно `tools/user.py::get_users(name=...)` в docstring обещает two-request merge path, но пока делает его последовательно.

## Цель

Снять основные perf/correctness риски:
- убрать грубый N+1 в inactive pets;
- сделать free-slot computation корректной по clinic boundary;
- зафиксировать pagination boundary;
- синхронизировать `get_users(name=...)` с обещанной parallel semantics.

## Scope

**В scope:**
- `tools/pet.py`
- `tools/_inactive_helpers.py`
- `tools/schedule.py`
- `tools/crud_helpers.py`
- `tools/user.py`
- `tests/test_inactive_pets.py`
- `tests/test_get_doctor_free_slots.py`
- `tests/test_crud_helpers.py`
- `tests/test_ergonomic_filters.py`

**Вне scope:**
- новые API endpoints;
- изменение LLM/user-facing response schema сверх нужного;
- общее переписывание schedule/inactive tools вне перечисленных hot paths.

## Подзадачи

### 125.1 Batched inactive-pets lookup (≤2 ч)

- перестать делать pet/invoice/medcard lookup per client;
- обрабатывать страницу inactive clients батчами;
- использовать bounded concurrency только там, где это реально уменьшает wall-clock, без потери детерминированности выдачи.

### 125.2 Chunk-safe helper for >100 pets (≤1 ч)

- `find_pets_at_client_last_visit` должен уметь работать с pet chunks ≤100;
- broad batch fetch допустим, но финальный match должен оставаться строгим по `last_visit_date` конкретного клиента.

### 125.3 Schedule correctness + parallel fetch (≤2 ч)

- `timesheet` и `admission` fetch в `get_doctor_free_slots` выполнять через `asyncio.gather`;
- busy intervals partition'ить по `clinic_id`, когда `clinic_id` не передан;
- admission из clinic A не должен блокировать clinic B.

### 125.4 Pagination TOCTOU fix (≤1 ч)

- `paginate_all` должен захватывать `totalCount` только с первой страницы;
- termination: `offset >= initial_total_count or len(records) < page_size`;
- boundary tests на 100/101 обязательны.

### 125.5 Parallel users name-search (≤30 мин)

- `get_users(name=...)` перевести на `asyncio.gather` для `last_name` и `first_name`;
- merge/dedup semantics не менять.

### 125.6 Regression run + audit (≤2 ч)

- targeted pytest по затронутым файлам;
- полный `docker compose --profile test run --rm test`;
- workflow audit и запись в `AssumptionLog.md`.

## Верификация

- `tests/test_inactive_pets.py` содержит perf-oriented regression на batched lookup и chunking;
- `tests/test_get_doctor_free_slots.py` содержит multi-clinic regression и parallel-fetch regression;
- `tests/test_crud_helpers.py` фиксирует boundary 100/101 и initial totalCount semantics;
- `tests/test_ergonomic_filters.py` фиксирует parallel `get_users(name=...)` path;
- full suite зелёный.

## Риски

- Batched inactive-pets lookup легко ломает ordering; выдача должна остаться в порядке inactive clients page order.
- Broad batch invoice/medcard fetch может дать false positives, если фильтрация по дате не будет перепроверяться client-side.
- Параллельный `timesheet` + `admission` fetch нельзя делать ценой потери current validation/overflow guards.
