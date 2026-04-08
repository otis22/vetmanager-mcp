# PRD: Этап 81 — Эргономические обёртки для типовых вопросов

## Цель

Выделить в самостоятельные MCP-tools две операции, которые LLM-у тяжело собрать из общих инструментов даже после этапа 78, потому что требуют правильного набора фильтров + сортировки + дефолтов одновременно.

## Проблема

Два наблюдаемых в прод-использовании сценария:

1. **«Когда у клиента/питомца следующий визит?»** — требует от LLM: `get_admissions` с `client_id=X`, `date_from=today`, активные статусы, sort ASC, limit. LLM стабильно пропускает 1–2 фильтра.

2. **«Покажи расписание клиники на сегодня»** / «расписание доктора на сегодня» — требует: `get_admissions` с `date=today`, активные статусы, sort по времени ASC. LLM часто забывает сортировку и возвращает хаотичный список.

## Кандидаты (оба реализуются как тонкие обёртки над `get_admissions`)

### 81.1 `get_client_upcoming_visits` — ≤1 ч

```python
@mcp.tool
async def get_client_upcoming_visits(
    client_id: int,
    pet_id: int = 0,
    date_from: str = "today",
    days: int = 90,
    limit: int = 20,
) -> dict:
    """List upcoming (future) appointments for a client or a specific pet.

    Returns admissions sorted by date ascending, excluding cancelled/deleted ones.

    Args:
        client_id: Required. The client whose visits to list.
        pet_id: Optional. If set, limit to admissions for this pet only.
        date_from: Start date (default: today). Accepts relative dates.
        days: Window length in days from date_from (default: 90).
        limit: Max records (1–100, default 20).
    """
```

Реализация: внутри вызывает `get_admissions` со собранным фильтром:
- `client_id=X`
- `patient_id=pet_id` если > 0
- `admission_date >= parse_date_param(date_from)`
- `admission_date <= date_from + days`
- status ∈ активные (`save`, `directed`, `accepted`, `in_treatment`, `delayed`, `not_confirmed`) через OR-filter или через пост-фильтрацию клиентского кода (выбор по результатам 78.3 OR-ресёрча).
- sort ASC по `admission_date`
- limit

### 81.2 `get_daily_schedule` — ≤1 ч

```python
@mcp.tool
async def get_daily_schedule(
    date: str = "today",
    doctor_id: int = 0,
    clinic_id: int = 0,
    limit: int = 100,
) -> dict:
    """List all appointments scheduled for a given date.

    Sorted by time ascending, excluding cancelled/deleted.

    Args:
        date: Date (YYYY-MM-DD or relative: today, tomorrow, +1d). Default: today.
        doctor_id: Optional. Filter to a specific doctor.
        clinic_id: Optional. Filter to a specific clinic.
        limit: Max records (1–100, default 100).
    """
```

Реализация: `get_admissions` с `date_from=date_to=date`, активные статусы, sort ASC по `admission_date`, опционально `user_id`/`clinic_id`.

### 81.3 Тесты и documentation — ≤1 ч

- Unit-тест: оба tool собирают правильный filter и sort.
- Mock e2e: happy path + пустой ответ.
- Tool descriptions с примерами диалога.

## Почему отдельные tools, а не одни параметры get_admissions

- **LLM-discoverability**: отдельный tool с говорящим именем выбирается моделью напрямую по названию. `get_admissions` с 8 параметрами — она может промахнуться в 1 из них.
- **Безопасные defaults**: `date_from=today` и sort ASC запечены в tool, LLM не может забыть.
- **Тонкая обёртка**: никакой дубликации логики — оба tool внутри вызывают один и тот же `get_admissions` с нужными аргументами. Стоимость поддержки минимальна.

## Зависимости

- Этап 78 (новые параметры `get_admissions`).
- Этап 79 (относительные даты в `date`/`date_from`).

## Acceptance

- [ ] Оба tool зарегистрированы, видны в `tools/list`.
- [ ] `get_client_upcoming_visits(client_id=X)` возвращает отсортированные по дате будущие приёмы, без deleted/not_approved.
- [ ] `get_daily_schedule()` без аргументов возвращает сегодняшнее расписание всей клиники.
- [ ] `get_daily_schedule(date="tomorrow", doctor_id=Y)` работает корректно.
- [ ] Тесты зелёные, Codex-ревью пройдено.

## Open assumptions

- **Активные статусы** выносятся в общую константу `tools/admission.py::ACTIVE_ADMISSION_STATUSES`, используется и здесь, и в этапе 80.
- **Decision**: делаем оба tool сразу (per user) — выкатываем вместе.
