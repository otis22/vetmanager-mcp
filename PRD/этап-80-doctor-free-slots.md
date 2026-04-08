# PRD: Этап 80 — `get_doctor_free_slots` (окна врача на неделю/2 недели/месяц)

## Цель

Дать LLM прямой ответ на типовой вопрос клиента: «Когда можно записать на приём к доктору Ивановой на следующей неделе?». Вернуть список конкретных свободных временных окон врача в заданном диапазоне (до 31 дня), пригодных для записи.

## Проблема и архитектурный выбор

В публичном REST API Vetmanager **нет эндпоинта «свободные окна»**. В legacy PHP это считается внутри приложения функцией `Timesheet::getDataForPlaning($startDate, $doctorsIds, $clinicId)`, которая не экспонируется наружу. Поэтому мы вычисляем свободные окна **на клиенте MCP**:

```
free_slots = (timesheet_intervals) MINUS (busy_intervals)
```

где `busy_intervals` — активные admissions врача за тот же период.

## Feasibility (проверено)

### Timesheet entity (`/rest/api/timesheet`)

| Поле | Тип | Назначение |
|---|---|---|
| `id` | int | PK |
| **`doctor_id`** | int | FK → user (⚠ не `user_id`, несовместимо с admission!) |
| `begin_datetime` | datetime | начало смены `YYYY-MM-DD HH:MM:SS` |
| `end_datetime` | datetime | конец смены |
| `clinic_id` | int | FK → clinic (multi-clinic support) |
| `all_day` | tinyint | 1 = все-дневная запись |
| `night` | tinyint | 1 = ночная смена |
| `title` | varchar(50) | описание |
| `type` | int | timesheet_types |

**Перерывы/обед отдельной сущностью не моделируются.** Врач с обедом представлен как **две timesheet-строки на один день** (например, `09:00–12:30` и `14:00–19:00`), и gap между ними = обед. Алгоритм `compute_free_slots` обрабатывает multi-row timesheet нативно, потому что работает с интервалами, а не с днями.

### Admission для busy-интервалов (`/rest/api/admission`)

- Фильтр: `user_id=doctor_id`, `admission_date >= from`, `admission_date <= to`.
- **Активные статусы** (считаются «занято»): `save`, `directed`, `accepted`, `in_treatment`, `delayed`, `not_confirmed`.
- **Игнорируем** (считаются «свободно»): `deleted`, `not_approved`.
- Длительность из `admission_length` (формат `HH:MM:SS`, nullable).
- **Fallback при NULL**: используем `slot_minutes` из параметров tool (default 30) — максимально безопасный вариант без доп. запроса к `userPosition`. В PRD фиксируем как MVP-упрощение; если real-API probe покажет, что NULL встречается регулярно, рассматриваем второй запрос к `userPosition` в итерации 2.

### Наружное vs внутреннее имя поля врача

API несогласовано: timesheet использует `doctor_id`, admission — `user_id`. Во внешнем API MCP-tool используем единое имя **`doctor_id`**, внутри мапим в правильное поле каждого endpoint'а. Фиксируем несоответствие в AssumptionLog.

## Сигнатура

```python
@mcp.tool
async def get_doctor_free_slots(
    doctor_id: int,
    date_from: str = "today",
    date_to: str = "+7d",
    slot_minutes: int = 30,
    min_slot_minutes: int = 15,
    clinic_id: int = 0,
) -> dict:
    """Return free appointment windows for a given doctor over a date range.

    Computed as (doctor timesheet work intervals) MINUS (active admissions).
    Breaks/lunches are represented implicitly via gaps between adjacent
    timesheet rows for the same day.

    Args:
        doctor_id: Required. Use get_users(name=...) to resolve a doctor by name first.
        date_from: Start date (YYYY-MM-DD or relative: today, +7d, -1w, etc.).
        date_to: End date (inclusive). Max range is 31 days.
        slot_minutes: Size of each free slot in minutes (default 30). Used
            both to chunk long free intervals and as fallback admission duration.
        min_slot_minutes: Discard gaps shorter than this (default 15).
        clinic_id: Optional clinic filter. 0 = all clinics where the doctor works.
    """
```

## Алгоритм (pure function)

```
compute_free_slots(
    work_intervals: list[(start_dt, end_dt)],
    busy_intervals: list[(start_dt, end_dt)],
    slot_minutes: int,
    min_slot_minutes: int,
) -> list[(start_dt, end_dt)]
```

1. Отсортировать `work_intervals` по start, смержить пересекающиеся (нормализация).
2. Отсортировать `busy_intervals`, смержить пересекающиеся.
3. Для каждого work-интервала: вычесть все пересечения с busy → получить список «щелей».
4. Для каждой щели длиной ≥ `min_slot_minutes`: нарезать на слоты по `slot_minutes`; остаток (< `slot_minutes`, но ≥ `min_slot_minutes`) вернуть как последний слот.
5. Вернуть плоский список.

## Декомпозиция

### 80.1 Real API probe — ≤1.5 ч

- Реально дёрнуть `/rest/api/timesheet?filter=[{"property":"doctor_id","value":<id>,"operator":"="},...]` через `TEST_DOMAIN`/`TEST_API_KEY`.
- Зафиксировать в AssumptionLog: точный формат `begin_datetime`/`end_datetime`, распределение по multi-row дням, частота `admission_length=NULL` в выборке, реальный набор статусов admission в тестовой базе.
- Проверить, что фильтры `>=`/`<=` работают на `begin_datetime` корректно (не лексикографически).

### 80.2 Pure-функция compute_free_slots — ≤2 ч

- `tools/_slots_helpers.py`.
- Функции: `merge_intervals`, `subtract_intervals`, `chunk_into_slots`, `compute_free_slots`.
- Работает с `datetime.datetime` (naive, в локальном TZ клиники — см. этап 79).
- Никаких сетевых вызовов, полностью тестируется in-memory.

### 80.3 Tool `get_doctor_free_slots` — ≤2 ч

- `tools/admission.py` или новый `tools/schedule.py` — обсудить; предпочтительно `tools/schedule.py` чтобы не раздувать admission.py.
- Валидации:
  - `doctor_id == 0` → `ValueError("doctor_id is required; use get_users(name=...) to resolve first")`.
  - Range > 31 day → `ValueError("date range cannot exceed 31 days")`.
  - `date_from > date_to` → `ValueError`.
  - `slot_minutes` в `[5, 240]`, `min_slot_minutes` в `[5, slot_minutes]`.
- Fetch timesheet через `paginate_all` (могут быть много строк при многомесячном запросе — хотя capped 31 днём).
- Fetch admissions через `paginate_all` с filter по активным статусам.
- Для admission парсить `admission_length`: `HH:MM:SS` → timedelta. Если пусто/NULL/`00:00:00` → `timedelta(minutes=slot_minutes)`.
- Группировка timesheet по `(doctor_id, clinic_id)` если `clinic_id==0` — returning slot записи должны нести `clinic_id` для UX.
- Формат ответа:

```json
{
  "success": true,
  "doctor_id": 42,
  "date_from": "2026-04-08",
  "date_to": "2026-04-15",
  "slot_minutes": 30,
  "slots": [
    {"start": "2026-04-08T09:00:00", "end": "2026-04-08T09:30:00", "clinic_id": 1, "duration_min": 30},
    {"start": "2026-04-08T09:30:00", "end": "2026-04-08T10:00:00", "clinic_id": 1, "duration_min": 30}
  ],
  "total_slots": 2
}
```

### 80.4 Unit-тесты compute_free_slots — ≤1.5 ч

- Пустой timesheet → пустой результат.
- Timesheet без admissions → нарезка на слоты по `slot_minutes`.
- Полностью занятый день (один admission на всю смену) → пусто.
- Два admissions подряд → один объединённый busy, одна щель до и после.
- Multi-row timesheet (обед) → два интервала свободного времени.
- Admission выходит за границу timesheet → обрезается границами timesheet.
- `admission_length=NULL` → fallback к `slot_minutes`.
- Щель `12` мин при `min_slot_minutes=15` → отбрасывается.
- Щель `45` мин при `slot_minutes=30, min_slot_minutes=15` → два слота: `0–30`, `30–45` (последний 15-мин).

### 80.5 Mock e2e тест tool — ≤1 ч

- Зафиксировать HTTP-моки: один запрос на timesheet, один на admission.
- Проверить формат ответа целиком.
- Проверить edge cases: invalid doctor_id, range > 31d.

### 80.6 Tool description + AssumptionLog — ≤30 мин

- Description: явная цепочка `get_users(name="Иванова") → get_doctor_free_slots(doctor_id=...)`.
- Known limitations: NULL admission_length → fallback; inconsistency `doctor_id` vs `user_id` между timesheet и admission; MVP не учитывает `all_day=1` и `night=1` флаги (документируем).
- AssumptionLog: результаты 80.1 probe, выбор fallback-стратегии.

## Acceptance

- [ ] Tool зарегистрирован, видим через `tools/list`.
- [ ] Все unit-тесты compute_free_slots зелёные.
- [ ] Mock e2e тест зелёный.
- [ ] Запрос с `date_from=date_to=today` возвращает слоты на один день.
- [ ] Запрос с range > 31 день → ValueError.
- [ ] Real API probe пройден на тестовой базе, результаты задокументированы.
- [ ] Codex-ревью пройдено.

## Open assumptions и MVP-ограничения

1. **all_day/night флаги timesheet** — MVP игнорирует. Строка `all_day=1` берётся как `00:00–23:59`; `night=1` обрабатывается как обычный интервал без special casing.
2. **Перерывы внутри одной timesheet-строки** — в API не представимы. Врач с обедом должен иметь две строки.
3. **NULL admission_length** — fallback к `slot_minutes`. Если probe покажет >30% NULL в прод-данных — второй запрос к `userPosition` в следующей итерации.
4. **Multi-clinic aggregation** — при `clinic_id=0` объединяем timesheet всех клиник врача; каждый слот несёт `clinic_id` в ответе. Пересечение смен в разных клиниках (maloвероятно, но возможно) — обрабатывается merge_intervals.
5. **Черновики/приватные admissions** — исключаем только `deleted` и `not_approved`. Остальные считаем «занято». Если клиника использует статусы иначе — документируем.
6. **TZ** — локальный TZ клиники из этапа 79, никаких конверсий.
