# PRD: Этап 77 — Inactive clients/pets через client.last_visit_date

## Цель
Оптимизировать поиск неактивных клиентов и питомцев. Заменить текущий 4-source paginated approach на серверный фильтр по `client.last_visit_date`. Добавить новый tool `get_inactive_clients`.

## Default параметры
- **Window**: 13-24 месяца назад (lapsed но не утраченные)
- **Limit**: top 50 (защита от accidental dump)
- **Sort**: `last_visit_date DESC` (most recently lapsed first)

## Алгоритмы

### get_inactive_clients
1. Calculate window: cutoff_oldest = today - months_max, cutoff_newest = today - months_min
2. Single API call: `/rest/api/client` with filters:
   - `status = ACTIVE`
   - `last_visit_date >= cutoff_oldest`
   - `last_visit_date <= cutoff_newest`
   - `sort = [last_visit_date DESC]`
   - `limit = 50` (или customized)
3. Return list with metadata

### get_inactive_pets (per-pet точный)
1. Fetch top inactive clients (с запасом — `client_fetch_limit = min(limit*3, 100)`)
2. Для каждого client (последовательно или малый concurrency):
   - Normalize last_visit_date к `YYYY-MM-DD 00:00:00`
   - Get all alive pets: `filter=[owner_id=client.id, status=alive]`
   - Для каждого pet: сначала invoice (`filter=[pet_id, invoice_date >= cutoff]`), затем medcard fallback
   - Если найдено — pet был на последнем визите, добавить в результат
3. Stop когда накоплено `limit` pets
4. Return list с client info + pet info + visit_source

## Bug fix: owner_id

В Vetmanager API таблица `pet` использует поле **`owner_id`** (FK к `client.id`).
Текущий код в `tools/pet.py::get_pets` принимает параметр `client_id` и передаёт его в API. Нужно проверить и привести к корректному `owner_id` на стороне фильтра.

Зафиксировать в AssumptionLog.

## Tool descriptions

Консистентно с другими (`get_debtors`, `get_pet_profile`):
- Явно указать default period (13-24 месяца)
- Явно указать default limit (50)
- Указать customization params
- Domain synonyms

## Производительность

- `get_inactive_clients`: 1 API call, ~50-200ms
- `get_inactive_pets` (default 50): ~100-300 API calls, ~5-15 сек с rate limiter
- Acceptable для on-demand reactivation tool

## Out of scope
- Background batch processing
- UI для reactivation campaigns
- Письма/уведомления
