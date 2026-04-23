# API research notes — Vetmanager

Документ для накопления **неочевидных знаний** об API Vetmanager, которых нет напрямую в `vetmanager_openapi_v6.json` или `api_entity_reference-ru.md`. Сюда попадают: расхождения между полями разных сущностей, подводные камни фильтрации, не описанные в OpenAPI поведения, выводы из legacy PHP-кода (`../vetmanager-extjs/`).

Каждая запись: **дата — источник — суть — влияние**. Новые записи — сверху.

---

## ⚠️ Поля и их реальные имена — чек-лист (читать ПЕРЕД ревью / правкой tools)

**Authoritative источники:**
1. `../vetmanager-extjs/application/src/Entity/*.php` и `rest/protected/models/*.php` — настоящий backend
2. `../support-bot-base/base/vetmanager_help/REST_API/*.md` — официальная публичная документация API
3. `artifacts/vetmanager_openapi_v6.json` — OpenAPI spec
4. Этот файл — накопленный опыт

**Путаница, на которой ловятся и люди, и LLM-ревьюеры:**

| Операция | Внешнее/интуитивное имя | **Реальное имя в API** | Источник |
|---|---|---|---|
| Admission → врач | `doctor_id` | **`user_id`** | `Entity/Admission.php:57-74`, `Dostup_k_priemam.md:10,63,73` |
| Admission → дата | `date` | **`admission_date`** (формат `Y-m-d H:i:s`) | `Dostup_k_priemam.md:6,68` |
| Admission → питомец | `pet_id` | **`patient_id`** | `Entity/Admission.php:57-74` |
| Admission → клиент | `client_id` | `client_id` ✓ | там же |
| Admission → status | `assigned` (нет такого!) | **enum:** `save`, `directed`, `accepted`, `deleted`, `delayed`, `not_approved`, `in_treatment`, `not_confirmed`. Дефолт при create в ORM — **`save`** | migration `m190218_081130_add_admission_not_confirmed_status.php` |
| Pet → владелец | `client_id` | **`owner_id`** | `models/Pet.php:18,32`, `Dostup_k_pitomtsam.md:6,47` |
| MedicalCards → питомец (CRUD filter) | `pet_id` | **`patient_id`** | `models/MedicalCards.php:9,55,75` |
| MedicalCards → питомец (specialized actions `MedicalcardsDataByClient`, `AddVaccination`) | — | **`pet_id`** (query-param, не filter) | `Dostup_k_medkartam.md:204,259,514` |
| Timesheet → врач | — | **`doctor_id`** ✓ | там же |
| Hospital create → питомец | `pet_id` | **`patient_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Hospital create/update → блок | `block_id` / `blockId` | **`hospital_block_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Hospital create/update → даты | `dateIn` / `dateOut` | **`date_in` / `date_out`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Payment create/list → клиент | `clientId` | **`client_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Payment create → касса | `cassaId` | **`cassa_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| InvoiceDocument create/list → счёт | `invoiceId` | **`invoice_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| InvoiceDocument create → товар/услуга | `goodId` | **`good_id`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Client create → имя/фамилия | `firstName` / `lastName` | **`first_name` / `last_name`** | super-review 2026-04-20 B1 + stage 122 contract fix |
| Client create → телефон | `phone` | **`cell_phone`** | roadmap 122.3 + stage 122 contract fix |
| Breed list filter → тип животного | `petTypeId` | **`pet_type_id`** | super-review 2026-04-20 medium finding + stage 122 contract fix |
| Timesheet date filter | top-level `date` query | **overlap predicate:** `begin_datetime < next_day 00:00:00` + `end_datetime > day_start 00:00:00` | stage 122 contract fix + stage 133 night-shift fix |

### Полный payload `POST /rest/api/admission` (canonical)

```json
{
  "admission_date": "2026-04-17 10:00:00",
  "client_id": 6,
  "patient_id": 42,
  "user_id": 1,
  "status": "save"
}
```

Поля `doctor_id`, `date`, `pet_id` в payload **молча игнорируются** — запись создаётся с NULL/дефолтами и исчезает из всех schedule-фильтров.

### Дополнительные canonical payload/query примеры (stage 122)

```json
POST /rest/api/hospital
{
  "patient_id": 42,
  "doctor_id": 1,
  "date_in": "2026-04-21 09:00:00",
  "hospital_block_id": 3
}
```

```json
POST /rest/api/payment
{
  "client_id": 6,
  "amount": 1500.0,
  "cassa_id": 1
}
```

```json
POST /rest/api/invoiceDocument
{
  "invoice_id": 50,
  "good_id": 2,
  "quantity": 1,
  "price": 250.0
}
```

```json
POST /rest/api/client
{
  "first_name": "Ivan",
  "last_name": "Petrov",
  "cell_phone": "+7 999 123-45-67"
}
```

### Урок ревью 2026-04-17

Baseline deep-review пропустил `pet_id` → `patient_id` в suggested_fix F1 потому что в inline-контексте Codex'у это было задекларировано неверно. Mitigation: все ревьюеры обязаны **читать этот раздел** при работе с tools, касающимися admission/medical_card/pet, и передавать его в промпт при Codex-эскалации.

---

## 2026-04-08 — ClientPhone endpoint для нормализованного поиска по телефону

**Источник:** `../vetmanager-extjs/rest/protected/models/ClientPhone.php`, `rest/protected/controllers/ClientPhoneController.php`, `application/src/Entity/ClientEntity.php::updateClearPhone()`. Real API probe на devtr6.

### Endpoint: `/rest/api/ClientPhone` (регистр важен)

- **Имя в URL**: `ClientPhone` с заглавными C/P. Варианты `clientPhone`, `client_phone`, `clientphone` возвращают 404.
- **Entity key в data**: `clientPhone` (camelCase) — вот так: `data.clientPhone: [...]`.
- **Поля**:
  - `client_id` (integer) — FK к client
  - `type` (enum): `"home"`, `"work"`, `"cell"`
  - `original_phone` (string) — как хранится в `client.home_phone`/`work_phone`/`cell_phone` со всем форматированием (например `"(918)414-02-59"`)
  - `clean_phone` (string) — **digits-only**, полученный через SQL `replace(replace(replace(replace(X, '-', ''), '(', ''), ')', ''), ' ', '')`
- **Доступен только `restList`** (filterRestAccessRules в контроллере режет всё кроме GET list). То есть можно фильтровать и получать, CRUD через этот endpoint нельзя.
- **Таблица-источник**: `clients_phones`. Заполняется автоматически через `ClientEntity::updateClearPhone($client_id)` на каждом create/edit клиента.

### Verified probe: фильтр `clean_phone LIKE`

```python
filter=[{"property": "clean_phone", "value": "9184140259", "operator": "LIKE"}]
# → {"client_id": 6, "type": "cell", "original_phone": "(918)414-02-59", "clean_phone": "9184140259"}
```

Работает корректно. Это решает deferred issue этапа 78 (поиск клиента по полному номеру телефона).

### Как использовать для поиска клиента по телефону

Двухфазный запрос:
1. `GET /rest/api/ClientPhone?filter=[{clean_phone LIKE digits}]` → список `client_id`.
2. `GET /rest/api/client?filter=[{id IN [ids]}]` → полные карточки клиентов.

### Ограничения

- Данные `clients_phones` ЖИВУТ на write-операциях через `ClientEntity::save/edit`. Если клиент правился через прямое SQL-обновление (не через entity), `clean_phone` может быть stale. На практике — в клиниках все апдейты идут через UI → ClientEntity, так что риск низкий.
- Не содержит исторических телефонов: только текущие `home_phone`/`work_phone`/`cell_phone`. Старый номер клиента после смены не найдётся.

---

## 2026-04-08 — Filter operator `IN` с list value

**Источник:** real API probe на devtr6.

`/rest/api/client?filter=[{"property":"id","value":[1,6],"operator":"IN"}]` возвращает клиентов с id=1 и id=6.

### Подтверждённые формы

| Форма value | Результат |
|---|---|
| `[1, 6]` (JSON list) | ✅ работает — возвращает 2 клиента |
| `[1, 6]` с `operator: "in"` (lowercase) | ✅ работает |
| `"1,6"` (comma-string) | ❌ возвращает только первого |

**Правило**: передавать value как JSON-array, не строку. Оператор регистр-независим.

### Потенциальные применения

- **Batch-fetch по ID**: `id IN [...]` заменяет N последовательных `GET /rest/api/entity/{id}` одним запросом. Экономит в случаях N+1 циклов.
- **Двухфазный поиск**: Phase 1 резолвит идентификаторы (например, `ClientPhone` → `client_id`), Phase 2 батчит `client?filter=[id IN [ids]]`.
- **Фильтр по множеству статусов**: `status IN ["save","accepted","directed"]` вместо клиентского пост-фильтра (см. этап 81, где сейчас это реализовано client-side).

### Ограничения

- Vetmanager limit на `limit` — 100 записей на страницу. Если резолвленных ID больше 100, нужна пагинация (или chunked IN запросы по 100).

---

## 2026-04-08 — Timesheet и свободные окна врача

**Источник:** OpenAPI v6 + `../vetmanager-extjs/ajax_calendar.php`, `Timesheet.php`, `UserRow.php` (research в рамках этапа 80).

### Расхождение имён: `doctor_id` vs `user_id`

- `/rest/api/timesheet` использует **`doctor_id`** как FK к user.
- `/rest/api/admission` использует **`user_id`** как FK к тому же самому user (врач, назначенный на приём).

Это один и тот же человек, но поле называется по-разному. При фильтрации по «врачу» нужно выбирать правильное имя для конкретного endpoint'а. MCP-tools наружу публикуют единое имя `doctor_id` и мапят внутри.

### Перерывы/обед не моделируются отдельно

Нет ни поля `break_*`, ни отдельной сущности. Врач с обедом представлен как **несколько timesheet-строк на один день**:

- строка 1: `2026-04-08 09:00:00` → `2026-04-08 12:30:00`
- строка 2: `2026-04-08 14:00:00` → `2026-04-08 19:00:00`

Gap `12:30–14:00` = обед. Алгоритмы расчёта свободного времени должны работать с multi-row timesheet как с самостоятельными интервалами.

### Нет публичного эндпоинта «свободные окна»

Legacy PHP использует приватный метод `Timesheet::getDataForPlaning($startDate, $doctorsIds, $clinicId)` и `UserRow::getDoctorsForDayCalendarByTimesheet()` — ни один из них не экспонирован в REST. Для MCP считаем на клиенте: `(timesheet intervals) MINUS (active admissions)`.

### `admission.admission_length` — nullable, fallback через `userPosition`

- В OpenAPI `admission.admission_length` объявлен как string `HH:MM:SS`, но по факту nullable и может быть `00:00:00`.
- Дефолтная длительность приёма хранится в `userPosition.admission_length` (non-null) — эту величину UI использует как fallback.
- Для MCP: MVP использует параметр `slot_minutes` как fallback без доп. запроса; долгосрочно — второй запрос к `userPosition` если NULL встречается часто.

### Multi-clinic: один врач в нескольких клиниках

`timesheet.clinic_id` обязателен. Один врач может иметь параллельные timesheet-строки в разных клиниках. При агрегации «все окна врача» нужно явно решить: объединять по всем клиникам или фильтровать по одной. Пересечение рабочих смен в разных клиниках маловероятно, но технически возможно.

### Статусы admission: что считать «занято»

В `admission.status` enum: `save`, `directed`, `accepted`, `deleted`, `delayed`, `not_approved`, `in_treatment`, `not_confirmed`.

- **Занимают слот (активные):** `save`, `directed`, `accepted`, `in_treatment`, `delayed`, `not_confirmed`.
- **Не занимают:** `deleted` (удалён), `not_approved` (не утверждён — по сути черновик).

Это согласовано с тем, как фронтенд рисует календарь. Фиксируем как константу `ACTIVE_ADMISSION_STATUSES` в коде MCP.

### `all_day` / `night` флаги timesheet

- `all_day=1` означает запись на весь день — `begin_datetime`/`end_datetime` всё равно заполнены (обычно `00:00:00–23:59:59`).
- `night=1` означает ночную смену; интервал может переходить через полночь одной строкой.
- Для фильтра конкретного дня нельзя использовать containment `begin_datetime >= day_start AND end_datetime <= day_end`: так теряются ночные смены. Использовать overlap predicate `begin_datetime < next_day 00:00:00 AND end_datetime > day_start 00:00:00`.

---

## 2026-04-08 — Filterability и операторы

**Источник:** OpenAPI v6 + анализ существующих MCP-tools.

### `admission_date` поддерживает `>=` / `<=`

Существующий код в `tools/admission.py::get_admissions` использует `operator: "like"` на строке даты — работает, но субоптимально. API принимает `>=` / `<=` как datetime-компараторы. Переключение даёт корректное поведение для range-запросов и не меняет семантику для запроса одного дня (эквивалентно `>= "DATE 00:00:00" AND <= "DATE 23:59:59"`).

### `invoice.payment_status` — тринарный, не бинарный

Enum: **`none` / `partial` / `full`**. Нет `paid` / `unpaid` — LLM часто путает. Отдельно есть `invoice.status` (workflow state): `exec` / `save` / `deleted`. Это два разных поля, их нельзя смешивать.

### `client.cell_phone` — основное поле телефона

В entity `client` есть: `cell_phone`, `home_phone`, `work_phone`, `phone_prefix`. Для поиска клиента по телефону использовать `cell_phone` с LIKE. `phone_prefix` — это код страны/оператора, хранится отдельно.

**Гипотеза требующая проверки на real API:** хранятся ли телефоны в нормализованном виде (только цифры) или с форматированием (`+7 (916) 123-45-67`). От этого зависит стратегия LIKE-поиска. MVP нормализует запрос под «только цифры», если прод покажет проблему — расширяем.

### `get_users.name` поиск: OR между полями — требует проверки

В entity `user` есть `first_name` и `last_name`. Для поиска «по ФИО» нужен OR между полями. Поддерживает ли Vetmanager filter API оператор OR внутри массива — не очевидно из OpenAPI.

- Если поддерживает: `filter=[{"property":"first_name","operator":"LIKE","value":"X","or":true}, {"property":"last_name","operator":"LIKE","value":"X","or":true}]` (точный синтаксис проверить).
- Если нет: два последовательных запроса с merge по `id`.

**Статус:** требует real API probe в этапе 78.3.

### `pet.owner_id` vs привычка называть `client_id`

FK от питомца к владельцу — это **`owner_id`**, не `client_id`. Зафиксировано в AssumptionLog (этап 77.8). Часто путают в issue-описаниях.

### `admission.patient_id` vs привычка называть `pet_id`

FK от приёма к питомцу — это **`patient_id`**. Аналогичная путаница. Внутри tools оставляем как в API, наружу MCP может публиковать `pet_id` для единообразия — в таком случае обязательно задокументировать mapping в docstring.

---

## 2026-04-08 — Полезные операции из legacy PHP (кандидаты для будущих tools)

**Источник:** `../vetmanager-extjs/ajax_*.php`.

Вещи, которые полезны для AI-ассистента, но ещё не обёрнуты в MCP:

| PHP endpoint | Операция | Потенциальный MCP-tool |
|---|---|---|
| `ajax_calendar.php::get_planned_clients_for_print` | Список запланированных клиентов на период по врачам | `get_daily_schedule` (этап 81.2) |
| `ajax_admission.php::get_planned_admissions_for_client_pet` | Будущие визиты клиента/питомца | `get_client_upcoming_visits` (этап 81.1) |
| `ajax_admission.php::getJournalInfo` | Клиническая сводка по приёму | кандидат — `get_admission_clinical_summary` |
| `ajax_calendar.php::copy_day` / `copy_week` | Копирование дня/недели расписания | не подходит для AI — админская операция |

---

## Как дополнять этот файл

- Каждый раз при исследовании API, которое раскрыло неочевидный факт (расхождение, limitation, поведение не из OpenAPI) — добавить запись сверху с датой и источником.
- Если факт потом опровергнут real API — **не удалять**, а добавить заметку «ОПРОВЕРГНУТО YYYY-MM-DD: …» под исходной записью. История ошибочных гипотез полезна.
- Если факт закрепился как стабильное свойство API — можно перенести в `api_entity_reference-ru.md` с коротким редирект-комментом здесь.
