# Этап 87. Post-migration consistency sweep

## Контекст

Baseline super-review 2026-04-17 и аудит этапа 86 выявили, что миграции stage 77.4 (Pet FK → owner_id), stage 78.6 (get_invoices.payment_status), stage 82-83 (IN-batch) и PRD этапа 80 (единое имя `doctor_id` для timesheet) прошли частично — несколько tool'ов и все MCP prompts ссылаются на legacy имена параметров.

## Цель

Закрыть сквозную тему «drift после миграций»: привести оставшиеся tools и prompts к актуальному API-контракту, чтобы LLM-клиент не натыкался на молча проглатываемые фильтры и `get_pets(client_id=...)` вызовы.

## Scope

**В scope:**
- `tools/pet.py::create_pet` — payload `client_id` → `owner_id`, rename параметра для согласованности с `get_pets`/`update_pet`
- `tools/operations.py::get_timesheets` — rename `user_id` → `doctor_id`, перевод с broken `extra={"userId": ...}` top-level query на filter
- `prompts.py` — 5 prompts используют устаревшие параметры или делают client-side работу вместо available API params

**Вне scope:**
- CI lint на grep legacy-паттернов — отдельная инфраструктурная задача (87.3 из Roadmap, отложено)
- tools/invoice.py create_invoice payload — требует проверки invoice entity в ExtJS (не подтверждена поломка)
- tools/finance.py, tools/clinical.py inconsistency extra{camelCase} vs filter — отложено

## Подзадачи

### 87.1 create_pet: owner_id в payload и параметре

Файл: `tools/pet.py:75-102`.

Текущее:
```python
async def create_pet(
    alias: str,
    client_id: int,
    ...
) -> dict:
    payload: dict = {"alias": alias, "client_id": client_id}
```

Fix:
- Rename параметра: `client_id` → `owner_id` (согласованно с `get_pets`/`update_pet`)
- Payload `{"owner_id": owner_id}` (реальное FK поле Pet entity)
- Обновить docstring

**Breaking change**: клиенты, вызывавшие `create_pet(client_id=X)`, сломаются. Вероятность нулевая — FK всегда был owner_id, текущий code был broken (пет создавался без владельца или с NULL owner, о чём никто не жаловался потому что tool мало используется).

LOC: ≤15.

### 87.2 get_timesheets: doctor_id параметр + filter

Файл: `tools/operations.py:50-70`.

Текущее:
```python
async def get_timesheets(
    ..., user_id: int = 0, date: str = "", ...
) -> dict:
    return await crud_list(
        "/rest/api/timesheet", ...,
        extra={"userId": user_id, "date": date},
    )
```

Проблема: `extra={"userId": user_id}` — top-level query, VM API для timesheet такое игнорирует. PRD этапа 80 явно зафиксировал единое внешнее имя `doctor_id`.

Fix:
- Rename параметра: `user_id` → `doctor_id`
- Filter-based передача: `[{"property": "doctor_id", "value": doctor_id, "operator": "="}]` вместо `extra{}`
- Параметр `date` оставляем как есть — это отдельный вопрос (может быть `begin_datetime` или `date` в API; проверка в отдельном этапе)

**Breaking change**: клиенты `get_timesheets(user_id=X)` сломаются. Опять — ранее параметр фактически не работал (игнорировался API), так что по факту это bug-fix без потери функциональности.

LOC: ≤20.

### 87.3 prompts.py sweep

Файл: `prompts.py`.

5 prompts переписать:

1. **book_appointment** (line 81-89): `get_pets(client_id=client_id, limit=100)` → `get_pets(owner_id=client_id, limit=100)`. `create_admission` call уже корректен после stage 86 (внешние имена сохранены).

2. **unconfirmed_appointments** (line 132-144): принимает одну дату вместо диапазона, фильтрует status client-side. Переписать: использовать `date_from=date, date_to=date+2d` и явно указать, что LLM должен вызвать `get_admissions(date_from=..., date_to=...)` — статус уже фильтруется на уровне API через `get_client_upcoming_visits` / `get_daily_schedule` (stage 81, 84). Актуально: обновить prompt на явный `status='not_confirmed'` — API filter на admission поддерживается.

3. **unpaid_invoices** (line 260-272): client-side фильтр. Перевести на `get_invoices(payment_status='none', limit=...)` + `get_invoices(payment_status='partial', limit=...)`.

4. **client_no_visit** (line 336-348): делает `get_admissions + ручной поиск last visit`. Есть tool `get_inactive_clients(months_min=..., months_max=..., limit=...)`. Переписать prompt на использование этого tool'а.

5. **search_good** (line 291-303): передаёт `name=query`, но primary параметр — `title`. Fix на `title=query`.

LOC: ≤80 (в основном текст prompt'ов).

### 87.4 Тесты

Добавить в `tests/test_api_contracts_hotfix.py` (или новый):

- `test_create_pet_payload_uses_owner_id` — mock POST /rest/api/pet, assert body содержит `owner_id` и НЕ содержит `client_id`
- `test_get_timesheets_filters_by_doctor_id` — mock GET, assert filter содержит `{property: doctor_id, operator: =}` и NOT `userId` в query
- `test_book_appointment_prompt_uses_owner_id` — mcp.get_prompt("book_appointment", ...) → текст содержит `owner_id=client_id`, не `client_id=client_id`
- `test_search_good_prompt_uses_title` — prompt text contains `title=query`
- `test_unpaid_invoices_prompt_uses_payment_status` — prompt text contains `payment_status='none'` и `payment_status='partial'`

LOC: ≤100.

### 87.5 Run tests + Codex review + commit + push

Стандартный workflow.

## Acceptance

- Все новые тесты проходят
- Полный test suite зелёный
- create_pet шлёт `owner_id` (mock verified)
- get_timesheets шлёт filter с `doctor_id` (mock verified)
- prompts не ссылаются на legacy имена параметров
- Codex review — 0 адекватных critical'ов
