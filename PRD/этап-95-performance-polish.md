# Этап 95. Performance polish — PBKDF2 to_thread + paginate_all max_rows + partial gather

## Цель

Закрыть несколько medium-performance findings с высоким ROI и низким regression risk: event-loop friendly password hashing, bounded pagination и partial-failure aggregation.

## Контекст

Baseline medium-performance findings. Выбираю 3 highest-ROI, наименее рискованных для финализации большого цикла 85-95.

## Scope

**В scope (95):**
- `web_auth.py::hash_account_password` / `verify_account_password` → `asyncio.to_thread` чтобы 390k PBKDF2 iterations не блокировали event loop на 80-150ms per login/register.
- `tools/crud_helpers.py::paginate_all`: default `max_rows=10_000` (было None → unbounded). Защита от OOM для листингов больших клиник.
- `tools/client.py::get_client_profile` и `tools/pet.py::get_pet_profile`: `asyncio.gather(..., return_exceptions=True)` + partial-failure поле в ответе. Одна упавшая секция не роняет весь агрегатор.

**Вне scope (→ 95b):**
- Async Redis client (wide refactor с тестами)
- request_cache deepcopy оптимизация (требует benchmarking)
- usage_stats ON CONFLICT upsert (dialect-aware SQL + alembic migration)
- DB индексы (alembic + deploy)

## Подзадачи

### 95.1 PBKDF2 via asyncio.to_thread

`web_auth.py`:
- `async def hash_account_password_async(password) -> str` — обёртка через `await asyncio.to_thread(hash_account_password, password)`
- То же для `verify_account_password_async`
- Callsite'ы в `web_routes_auth.py::register_submit` и `login_submit` переключаются на async-варианты
- Синхронные оригиналы оставляем (migration path for tests / non-async callers)

LOC: ≤40.

### 95.2 paginate_all default max_rows

`tools/crud_helpers.py::paginate_all`:
- `max_rows: int | None = None` → `max_rows: int = 10_000`
- Callers, которым нужно больше, передают явный `max_rows=...`
- Docstring обновить

LOC: ≤10.

### 95.3 asyncio.gather return_exceptions в профиль-агрегаторах

`tools/client.py::get_client_profile` и `tools/pet.py::get_pet_profile`:
- `asyncio.gather(..., return_exceptions=True)`
- Каждую секцию проверять: если `isinstance(result, Exception)` — положить `{"error": str(result)}` вместо данных + set `partial: True`

LOC: ≤40.

### 95.4 Тесты

- `test_hash_password_runs_in_thread_pool` — callsite doesn't block (synthetic timing if possible, or just assert coroutine).
- `test_paginate_all_default_max_rows_caps_runaway` — mock endpoint returning totalCount=20_000, assert ValueError.
- `test_get_client_profile_partial_on_section_failure` — one of 3-4 gather'ов roняет exception, итог имеет `partial: True` и остальные поля.

### 95.5 Codex review + commit

## Acceptance

- Login/register не блокирует event loop (верифицировано прямым await asyncio.to_thread wrap).
- paginate_all по дефолту capped в 10k rows.
- get_client_profile / get_pet_profile с одним failing section возвращает partial result.
- Full suite зелёный.
