# PRD: Этап 79 — Helper относительных дат для date-параметров

## Цель

Устранить класс ошибок, когда LLM передаёт в date-параметры значения вроде `"today"`, `"tomorrow"`, `"-7d"`, `"+2w"` — и получает либо пустой ответ (API интерпретирует это как литеральный фильтр), либо validation error. Принимать человеческие относительные даты во всех MCP-tools, где есть date-параметры.

## Контекст

API Vetmanager возвращает и принимает даты **в часовом поясе клиники** по умолчанию. Нам не нужно ни извлекать TZ, ни конвертировать — helper работает с локальной датой как `datetime.date.today()` в контейнере, и это считается локальным временем клиники (контейнер запускается в её TZ через env/mount).

## Поддерживаемый синтаксис

| Вход | Результат |
|---|---|
| `""` | `""` (без фильтра) |
| `"YYYY-MM-DD"` (валидный) | as-is |
| `"today"` | сегодняшняя дата |
| `"yesterday"` | вчера |
| `"tomorrow"` | завтра |
| `"+Nd"` / `"-Nd"` | сегодня ± N дней (N ≥ 0, integer) |
| `"+Nw"` / `"-Nw"` | сегодня ± N×7 дней |
| `"+Nm"` / `"-Nm"` | сегодня ± N календарных месяцев (через `dateutil.relativedelta` или самописный month-math) |
| невалидный формат | `ValueError` с перечислением поддерживаемых форматов |

Регистр нечувствителен (`TODAY` == `today`). Пробелы по краям — trim.

## Декомпозиция

### 79.1 Реализация helper — ≤1.5 ч

Файл `validators/dates.py`:

```python
def parse_date_param(value: str, *, today: date | None = None) -> str:
    """Convert a relative or absolute date spec to YYYY-MM-DD.

    Returns empty string if value is empty. Raises ValueError on invalid format.
    `today` arg exists for deterministic unit tests.
    """
```

- Чистая функция, никакой зависимости от I/O.
- `today` default = `datetime.date.today()`.
- Month-math: если в проекте уже есть `dateutil`, использовать `relativedelta`; иначе — простая реализация с clamping на конец месяца (31 января + 1 месяц = 28/29 февраля).
- Проверить наличие `dateutil` в 79.1.a перед выбором подхода.

### 79.2 Применение в существующих tools — ≤1.5 ч

Обновить следующие функции, оборачивая каждый date-параметр через `parse_date_param`:

- `tools/admission.py::get_admissions` — `date`, `date_from`, `date_to` (после этапа 78).
- `tools/invoice.py::get_invoices` — `date_from`, `date_to`.
- `tools/invoice.py::get_average_invoice` — `date_from`, `date_to`.
- `tools/client.py::get_inactive_clients` — если есть date-параметры.
- `tools/pet.py::get_inactive_pets` — если есть date-параметры.
- Подготовить точку применения для `get_doctor_free_slots` (этап 80).

Tool descriptions обновляются: в каждом date-параметре добавляется «accepts YYYY-MM-DD or relative forms: today, yesterday, tomorrow, +7d, -2w, +1m».

### 79.3 Тесты — ≤1 ч

`tests/validators/test_dates.py`:
- Все валидные форматы → ожидаемое значение (с фиксированным `today=date(2026,4,8)`).
- Граница месяца: `today=2026-01-31`, `+1m` → `2026-02-28`.
- Високосный год: `today=2024-01-31`, `+1m` → `2024-02-29`.
- Невалидные: `"nextweek"`, `"2026/04/08"`, `"-d"`, `"+1y"` (года не поддерживаем в MVP) → `ValueError`.
- Пустая строка → пустая строка.
- Регистр: `"TODAY"`, `"  today  "` → работают.

Интеграционные тесты на существующих tools: передаём `date_from="today"` и проверяем, что в httpx-mock уходит правильная дата.

## Acceptance

- [ ] `parse_date_param("today")` в тесте с fixed today возвращает правильную строку.
- [ ] `parse_date_param("")` → `""`.
- [ ] `parse_date_param("garbage")` → `ValueError` с текстом, перечисляющим поддерживаемые форматы.
- [ ] Все tools из 79.2 принимают относительные даты, old absolute формат работает без изменений.
- [ ] Tool descriptions обновлены.
- [ ] Mock e2e тест: `get_admissions(date_from="-7d", date_to="today")` → в payload уходят реальные даты недели.

## Open assumptions

- **Года (`+1y`)** не поддерживаем в MVP — редкий сценарий, можно добавить позже без breaking change.
- **Часовой пояс контейнера** — считаем что задаётся извне (TZ env переменная или совпадает с клиникой). В тестах используем fixed `today` для детерминизма.
- **Локализованные слова** (`сегодня`, `вчера`) не поддерживаем — tool descriptions на английском, LLM сам переводит.
