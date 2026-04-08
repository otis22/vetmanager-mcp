# PRD: Этап 78 — Ergonomic filters для LLM-discoverability

## Цель

Устранить класс ошибок, когда LLM не может воспользоваться MCP-инструментом потому что нужный фильтр доступен только через generic `filter=[{"property":...,"operator":"...","value":"..."}]`. LLM практически никогда не собирает такой фильтр самостоятельно — ему нужны именованные параметры, которые он увидит в tool schema.

## Проблема

Наблюдаемо в проде (`vetmanager-ai-assistant`, 2026-04-08): запрос «профиль Барсик» завершился ошибкой валидации `get_pets(name="Барсик")` — параметра `name` нет, есть только generic `filter`, который модель не использует. Аналогичная проблема присутствует во всех list-tools, где есть очевидные сценарии поиска по телефону клиента, названию товара, дате приёма, врачу и т.д.

## Принцип

Все новые параметры — **синтаксический сахар над существующим filter-контрактом**, без изменения поведения REST API. Старые вызовы с generic `filter=[...]` продолжают работать. Новые параметры комбинируются с переданным пользователем `filter` через объединение (append), не замещение.

Safety-rule: если параметр в принципе может вернуть «не того» пациента при слишком коротком/неуникальном значении — требуем парный якорь (см. 78.1) или минимальную длину (см. 78.2).

## Feasibility (проверено по OpenAPI v6 + api_entity_reference)

| Param | Endpoint | Field | Operator | Примечания |
|---|---|---|---|---|
| `get_pets.alias` | `/rest/api/pet` | `alias` | LIKE | FK владельца — **`owner_id`**, не `client_id` |
| `get_clients.phone` | `/rest/api/client` | `cell_phone` | LIKE | нормализация обязательна (см. 78.2) |
| `get_clients.email` | `/rest/api/client` | `email` | LIKE | |
| `get_users.name` | `/rest/api/user` | `first_name`/`last_name` | LIKE | OR между двумя полями (проверить поддержку OR в реальном API, fallback — два запроса + слияние) |
| `get_users.position_id` | `/rest/api/user` | `position_id` | = | |
| `get_users.is_active` | `/rest/api/user` | `is_active` | = | 0/1 |
| `get_admissions.date_from/to` | `/rest/api/admission` | `admission_date` | `>=`/`<=` | сейчас код использует `LIKE` по строке даты — переключить |
| `get_admissions.doctor_id` | `/rest/api/admission` | `user_id` | = | наружное имя `doctor_id` для ясности |
| `get_admissions.pet_id` | `/rest/api/admission` | `patient_id` | = | наружное имя `pet_id` для единообразия с `get_pets` |
| `get_admissions.client_id` | `/rest/api/admission` | `client_id` | = | |
| `get_goods.title` | `/rest/api/good` | `title` | LIKE | |
| `get_goods.group_id` | `/rest/api/good` | `group_id` | = | |
| `get_goods.is_active` | `/rest/api/good` | `is_active` | = | |
| `get_invoices.payment_status` | `/rest/api/invoice` | `payment_status` | = | enum: `none`, `partial`, `full` (не бинарный) |
| `get_invoices.pet_id` | `/rest/api/invoice` | `pet_id` | = | |

Admission status enum (для docstring): `save`, `directed`, `accepted`, `deleted`, `delayed`, `not_approved`, `in_treatment`, `not_confirmed`.

## Декомпозиция

### 78.1 `get_pets.alias` (paired с `owner_id`) — ≤1 ч

- Добавить параметр `alias: str = ""` в `tools/pet.py::get_pets`.
- Если `alias` непустой и `owner_id == 0` → `ValueError("alias filter requires owner_id — pet aliases are not unique per clinic")`.
- Если указан → добавить в filter `{"property":"alias","value":alias,"operator":"LIKE"}`.
- Обновить docstring: явная инструкция «для поиска по кличке сначала найди владельца через `get_clients`, затем передай `owner_id` и `alias` вместе».
- Тесты: standalone alias → error; paired → filter assembled; owner без alias → unchanged.

**Решение по issue #4**: используем **`owner_id`** (консистентно с существующим параметром `get_pets`), issue обновляется после мержа. Никаких `client_id` алиасов.

### 78.2 `get_clients.phone` + `get_clients.email` — ≤2 ч

- Helper `validators/phone.py::normalize_phone_digits(raw) -> str`: убирает всё, кроме цифр. Возвращает строку цифр.
- В `get_clients`: параметр `phone: str = ""`. Если задан:
  - нормализуем → если `len(digits) < 4` → `ValueError("phone filter requires at least 4 digits")`.
  - добавляем в filter `{"property":"cell_phone","value":digits,"operator":"LIKE"}`.
- **Известное ограничение**: если в БД телефоны хранятся с форматированием (`+7 (916) 123-45-67`), LIKE по чистым цифрам не сработает. Документируем в description и в AssumptionLog как «known gap, зависит от data hygiene клиники». В MVP делаем LIKE по нормализованной строке; если тесты на реальном API покажут проблему — расширяем.
- Параметр `email: str = ""` → filter LIKE на `email`, без нормализации.
- Тесты: короткий phone → error, нормализация, email LIKE.

### 78.3 `get_users.name` + `position_id` + `is_active` — ≤1.5 ч

- `get_users(name: str = "", position_id: int = 0, is_active: bool = True, ...)`.
- `is_active=True` по умолчанию: фильтр `is_active=1`. Если пользователь явно передал `is_active=False` → `is_active=0`. Если хочется «все» — оставить текущее поведение через generic `filter`.
- `name` — **OR-поиск**: в research-фазе 78.3.a проверить, поддерживает ли API Vetmanager OR в filter-массиве (смотря на PHP-код, обычно это `WHERE (first_name LIKE X OR last_name LIKE X)`). Если поддерживает — один запрос. Если нет — два последовательных запроса + merge по `id` (дубликаты исключить). Выбор зафиксировать в AssumptionLog.
- Тесты: name OR работает, position_id работает, is_active default.

### 78.4 `get_admissions` расширение + bugfix — ≤2 ч

- Новые параметры: `date_from: str`, `date_to: str`, `doctor_id: int = 0`, `pet_id: int = 0`, `client_id: int = 0`.
- `doctor_id` мапится в filter по `user_id`, `pet_id` — в `patient_id` (внешнее имя осознанно отличается от внутреннего, чтобы консистентно с остальными tools).
- **Bugfix**: текущий параметр `date` использует `LIKE` по строке даты. Заменить на пару `>=`/`<=` в рамках одного дня: `{admission_date >= "DATE 00:00:00", <= "DATE 23:59:59"}`. Параметр `date` оставляем для back-compat — он эквивалентен `date_from=date_to=date`.
- Если указаны оба `date` и `date_from`/`date_to` → `ValueError("use either `date` or `date_from`/`date_to`, not both")`.
- Docstring: полный enum status, примеры.
- Тесты: каждый новый фильтр отдельно + комбинация, back-compat для `date`.

### 78.5 `get_goods.title` + `group_id` + `is_active` — ≤1 ч

- Аналогично 78.3, без особенностей. Тесты стандартные.

### 78.6 `get_invoices.payment_status` + `pet_id` — ≤1 ч

- Параметр `payment_status: str = ""`. Валидация: если задан, должен быть в `{"none","partial","full"}`, иначе `ValueError`.
- Параметр `pet_id: int = 0`.
- Docstring: явно что `payment_status` — это статус оплаты, а не статус workflow счёта (там поле `status` с enum `exec`/`save`/`deleted`).
- Тесты: валидация enum, фильтр работает.

### 78.7 Тесты — параллельно с каждым пунктом

- Unit на сборку filter (проверка что именно попадает в HTTP-payload через mock client).
- Mock e2e на happy path.
- Валидационные ошибки → `pytest.raises`.

## Acceptance

- [ ] Все 6 инструментов имеют новые параметры, вызовы без них работают как раньше.
- [ ] `get_pets(alias="X")` без `owner_id` → ValueError с понятным текстом.
- [ ] `get_clients(phone="1234")` → фильтр собран по `cell_phone` LIKE `1234`; `phone="12"` → ValueError.
- [ ] `get_admissions(date="2026-04-08")` по-прежнему работает и возвращает только один день (через >=/<=, не LIKE).
- [ ] `get_invoices(payment_status="paid")` → ValueError (нет такого enum).
- [ ] Все тесты зелёные, Codex-ревью пройдено.

## Open assumptions

- **OR в filter для get_users.name** — проверяется в 78.3, fallback описан.
- **Формат хранения cell_phone** — assume чистые цифры; если прод покажет обратное, делаем отдельный тикет на полноценную нормализацию с учётом `phone_prefix`.
- **Back-compat для `get_admissions.date`** — оставляем, в docstring помечаем как «prefer date_from/date_to».
