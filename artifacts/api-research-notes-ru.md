# API research notes — Vetmanager

Документ для накопления **неочевидных знаний** об API Vetmanager, которых нет напрямую в `vetmanager_openapi_v6.json` или `api_entity_reference-ru.md`. Сюда попадают: расхождения между полями разных сущностей, подводные камни фильтрации, не описанные в OpenAPI поведения, выводы из legacy PHP-кода (`../vetmanager-extjs/`).

Каждая запись: **дата — источник — суть — влияние**. Новые записи — сверху.

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
- `night=1` означает ночную смену; интервал может переходить через полночь (проверить на real API, MVP не делает special casing).

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
