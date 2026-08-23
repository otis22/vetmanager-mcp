# Этап 239. Контракт сортировки у list-инструментов

## Цель

Не позволять MCP-клиенту угадывать REST-поле в публичном параметре `sort`.
Неизвестное или приватное имя должно отклоняться локально до HTTP-вызова с
перечнем подтверждённых имён. Регрессия Sentry PYTHON-8 —
`get_admissions(sort=[{"property": "date_admission"}])` — должна подсказать
`admission_date`.

## Проверенные факты

- `build_list_query_params` сериализует `sort` и `filter` без маппинга;
  `crud_list` уже является общей точкой filter-валидации для 24 проверенных
  сущностей.
- Read-only probe на `devtr6` 23.08.2026 получил по одной записи каждой
  сущности, выделил все 262 скалярных поля и отправил по одному `sort` с
  направлением `ASC`: 260 HTTP 200 и только `admission.wait_time` и
  `hospital.in_hospital_time` получили HTTP 406. Эти два response-only поля
  уже отсутствуют в filter-артефакте. Следовательно, обе стороны равенства
  проверены: допустимое множество sort-полей совпадает с filter-полями.
  Дата, режим `ASC`, окружение и счётчики записываются в versioned artifacts.
- Поэтому допустимое множество sort-полей совпадает с filter-полями и
  `FILTER_FIELDS_BY_ENTITY` остаётся единственным реестром. Поля
  `client.passport_series` и `user.calc_percents`, `last_change_pwd_date`,
  `login`, `passwd`, `user_inn` были приняты upstream-пробой, но вычтены из
  публичного реестра; это тот же privacy boundary для сортировки.
- Транспорт живых интеграций Claude и ChatGPT не меняется: меняется только
  локальная семантика уже существующего аргумента инструмента до обращения к
  Vetmanager.

## Декомпозиция

1. Расширить opt-in probe подтверждённых list endpoints режимом `sort`:
   получать scalar keys записи, сверять их с versioned filter snapshot и
   проверять каждый sort (≤150 строк).
2. Добавить общую локальную проверку `sort[].property` в `crud_list`, не
   меняя wire-format и сохранив аварийный kill switch (≤150 строк).
3. Передать один allowlist всем 24 уже проверенным public list-инструментам и
   дополнить их docstrings допустимыми sort-полями (≤2 ч за пачку файлов).
4. Добавить unit/mock-e2e регрессию `date_admission` → `admission_date`,
   privacy regressions и проверить отсутствие HTTP-вызова (≤150 строк).

## Архитектурное решение

### Проблема и ограничения

`sort` — публичный MCP-контракт, и ошибочный запрос достигает upstream как
HTTP 406. Нельзя расширять контракт непроверенными полями; нельзя создавать
второй список, который может разойтись с фильтрами. Сортировка по приватному
полю способна направлять выборку и потому является способом извлечения данных.

### Рассмотренные варианты

1. Только перечислить поля в docstring. Не даёт локального отказа и оставляет
   406 — отклонён.
2. Вести отдельный `SORT_FIELDS_BY_ENTITY`. Проба доказала равенство, но
   дублирование создаёт drift — отклонён.
3. Применить `FILTER_FIELDS_BY_ENTITY` и к `sort` в `crud_list`. Выбран:
   единый проверенный источник, одна privacy-граница, неизменный transport.

### Выбранное решение

`filters.py` получает симметричную `validate_sort_properties`, которая
проверяет только строковые `property` из элементов `sort`. `crud_list`
вызывает её до `build_list_query_params` из уже существующего единственного
`allowed_filter_properties`: у проверенного filter-tool это автоматически
включает тот же подтверждённый sort-guard без второго параметра. Ошибка
называет `Unknown sort property '<name>'. Did you mean '<canonical>'? Allowed
properties: ...`, если `difflib` находит близкое подтверждённое имя; иначе
содержит только отсортированный список. Форма sort, direction, пустые и
нестандартные элементы сохраняют прежнюю downstream semantics.

`SORT_CONTRACT_VALIDATION_ENABLED=0|false|no|off` временно возвращает прежний
sort passthrough, не ослабляя filter privacy-guard; unset/default остаётся
включённым. Публичные docstrings каждого проверенного инструмента называют
допустимые поля как для filter, так и для sort.

### Инварианты, риски и rollback

- HTTP JSON `sort` не меняется для разрешённых полей; Claude/ChatGPT transport
  не затрагивается.
- Непроверенные инструменты не получают новый allowlist и сохраняют своё
  поведение.
- Никакое поле из `public_excluded_fields` не публикуется и не принимается
  ни в filter, ни в sort.
- Если upstream contract изменится, оператор временно отключает только новый
  sort guard через `SORT_CONTRACT_VALIDATION_ENABLED=0`; постоянный rollback
  — убрать validator, не затрагивая filter guard.

Architecture Critique: required — меняется публичный MCP contract и
production behaviour отказа до upstream.

## Acceptance criteria

1. Versioned opt-in probe получает scalar keys записи, умеет проверять `sort`
   и подтверждает обе стороны совпадения с filter для 24 сущностей на
   `devtr6` без вывода значений/секретов; artifacts содержат provenance
   (дата, окружение, ASC, 260 accepted и 2 rejected response-only fields).
2. Все 24 уже проверенных public list-инструмента локально отклоняют
   неизвестный `sort[].property` с допустимыми именами; непроверенные не
   меняются.
3. Docstrings этих инструментов объявляют допустимые sort-поля.
4. `get_admissions` с `date_admission` не выполняет HTTP-вызов и отвечает
   точной подсказкой `Did you mean 'admission_date'?`; разрешённый sort
   по-прежнему сериализуется.
5. Приватные поля клиентов и сотрудников блокируются одинаково для filter и
   sort; полный mock suite и opt-in real probe зелёные.
