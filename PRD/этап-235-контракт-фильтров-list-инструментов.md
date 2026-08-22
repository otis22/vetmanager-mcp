# Этап 235. Контракт фильтров у list-инструментов

## Цель

Убрать необходимость угадывать имя REST-поля в публичном параметре `filter`
у пилотных финансовых list-инструментов. Неизвестный `property` должен
отклоняться локально с точным списком разрешённых имён, а не доходить до
Vetmanager как HTTP 406.

## Проверенные факты

- `filters.as_dict_list`, `filters.build_list_query_params` и
  `tools.crud_helpers.crud_list` передают `filter[].property` в upstream без
  маппинга.
- `get_cassa_closes`, `get_payments` и `get_invoices` принимают публичный
  passthrough `filter`; в отличие от `get_medical_cards_by_date`,
  `get_invoice_documents` и `get_doctor_free_slots`, они не скрывают его за
  дружественными именованными параметрами.
- Read-only probe на `devtr6` 22.08.2026 подтвердил, что у `cassaclose`,
  `payment` и `invoice` фильтруется каждое возвращаемое скалярное поле;
  несуществующий `close_date` у `cassaclose` детерминированно даёт HTTP 406.
- PHP-модели используются только для понимания сущности; в репозиторий
  переносится исключительно перечень имён, заново подтверждённый real probe.
- Текущий AST-инвентарь на 22.08.2026 нашёл 36 (а не указанные в постановке
  38) зарегистрированных tool-функций с публичным `filter`. Все они остаются
  passthrough; часть дополнительно имеет именованные параметры, но это не
  маппинг-семейство. Расхождение с Roadmap — historical count, не основание
  расширять этот ход.

### Инвентаризация

| Семейство | Инструменты | Решение этого хода |
| --- | --- | --- |
| Passthrough: finance | `get_payments`, `get_closing_of_invoices`, `get_invoice_documents`, `get_cassas`, `get_cassa_closes`, `get_invoices` | Пилот только `payments`, `cassa_closes`, `invoices`; `invoice_documents` сохраняет отдельный stage-161 mapping; остальные — 235.5 |
| Passthrough: entities | `get_admissions`, `get_clients`, `get_hospitalizations`, `get_hospital_blocks`, `get_diagnoses`, `get_medical_cards`, `get_pets`, `get_users` | 235.5 |
| Passthrough: operations | `get_clinics`, `get_timesheets`, `get_properties`, `get_anonymous_clients` | 235.5 |
| Passthrough: reference | `get_breeds`, `get_pet_types`, `get_cities`, `get_city_types`, `get_streets`, `get_units`, `get_roles`, `get_user_positions`, `get_combo_manual_names`, `get_combo_manual_items` | 235.5 |
| Passthrough: warehouse | `get_good_groups`, `get_good_sale_params`, `get_party_accounts`, `get_party_account_docs`, `get_store_documents`, `get_suppliers` | 235.5 |
| Passthrough: commerce | `get_goods` | 235.5; `name` остаётся extra-параметром |

`get_message_reports` входит в operations (пятая позиция) и сохраняет extra-параметр
`campaign`. Именованные параметры у других перечисленных tools также
сохраняются; они не являются поводом менять raw `filter` в этом ходе.

`get_medical_cards_by_date` и `get_doctor_free_slots` не входят в 36:
публичного raw `filter` у них нет, их маппинг не трогается.

## Декомпозиция

1. Инвентаризировать фактические 36 публичных `filter`-инструментов и отделить
   passthrough/маппинг; в данном ходе менять только три пилотных (≤2 ч).
2. Добавить opt-in probe: получить одну запись, проверить только её скалярные
   ключи и печатать лишь `endpoint field HTTP-status` (≤150 строк).
3. Вынести подтверждённые наборы полей пилота в data-модуль, проверить их
   тестом против versioned probe-артефакта и валидировать raw `property` до
   HTTP-вызова (≤150 строк вместе с тестами).
4. Дополнить docstrings и регрессию `close_date` → подсказка `date`; запустить
   mock и opt-in real контуры (≤2 ч).
5. Оставить 235.5 `todo`: остальные сущности требуют отдельной проверки
   реализации и поведения по пачкам 5–7.

## Архитектурное решение

### Проблема и ограничения

Raw `filter` — часть публичного MCP-контракта. Общая глобальная валидация
сейчас была бы недостоверной: большая часть list-инструментов ещё не
проверена, а инструменты с именованным маппингом имеют другой контракт.
Probe не должен записывать или печатать значения строк, ключи или секреты.

### Рассмотренные варианты

1. Описать поля только в docstrings. Это помогает модели, но ошибочный запрос
   всё ещё получает непрозрачный HTTP 406 — отклонён.
2. Добавить универсальный allowlist для всех list-инструментов. Это изменит
   непроверенные контракты и затронет маппинг-инструменты — отклонён.
3. Хранить малый allowlist по пилотному endpoint и вызывать валидацию только
   из трёх подтверждённых tools. Выбран: локальный, обратимо расширяемый и не
   меняет остальную поверхность.

### Выбранное решение

`filters.py` хранит неизменяемые публичные allowlist'ы для `cassaclose`,
`payment`, `invoice`. `crud_list` — единственная точка локальной проверки:
пилотные tools передают ему allowlist после построения собственных именованных
constraints. Поэтому raw и именованные filters проверяются одинаково, а уже
существующее специальное сообщение `get_payments` для `client_id` остаётся
приоритетным. Функция сообщает неизвестное имя и отсортированный список
допустимых имён, но не валидирует оператор или значение.

`FILTER_CONTRACT_VALIDATION_ENABLED=0|false|no|off` — аварийный runtime kill
switch: при каждом вызове он временно возвращает прежний passthrough. Unset,
пустое или другое значение означает default `1`. Изменение env требует
стандартного restart контейнера, но не code deploy; switch не расширяет
allowlist и служит только rollback при доказанном drift upstream.

`scripts/probe_list_filter_contract.py` — явный opt-in read-only инструмент:
он читает `TEST_DOMAIN`/`TEST_API_KEY`, получает `limit=1`, извлекает только
скалярные ключи и повторяет GET с константным значением `0`, не выводя
значений строки. На подтверждённом снимке это 3 list-запроса и 38
filter-запросов с паузой 100 ms (41 request total); если upstream вернёт
другой набор ключей, скрипт выводит все их статусы и CI/оператор сравнивает
его с artifact, а не молча обрезает набор. Скрипт отказывается работать вне
`TEST_DOMAIN=devtr6`. JSON-артефакт содержит
только endpoint и имена подтверждённых полей; unit test сверяет data-модуль с
artifact как provenance check, а актуальность allowlist подтверждает opt-in
real probe в этом ходе и при будущих изменениях.

### Инварианты, риски и rollback

- Допустимы только поля, подтверждённые реальной пробой данного endpoint;
  никаких PHP-деталей, значений записей и секретов в artefact нет.
- При отсутствии/пустом `filter` поведение и HTTP-вызов не меняются.
- `get_payments` по-прежнему запрещает raw `client_id` и сохраняет свои
  именованные date/status правила; их производные `create_date`/`status`, как
  и invoice named filters, входят в тот же подтверждённый allowlist.
- Mapping-инструменты не вызывают новый код. Rollback без deploy —
  `FILTER_CONTRACT_VALIDATION_ENABLED=0`; постоянный rollback — удалить
  pilot allowlist и три явных аргумента `crud_list`.
- Ошибка приходит в стандартном MCP `ToolError` от `ValueError` с шаблоном
  `Unknown filter property '<name>'. Allowed properties: <sorted names>.`;
  сравнение имён строгое, case-sensitive. Нестроковый или отсутствующий
  `property` сохраняет прежнюю downstream validation semantics.

Architecture Critique: required — меняется публичный MCP contract и поведение
отказа до upstream.

## Acceptance criteria

1. Инвентаризация фактических 36 инструментов и historical расхождения с 38
   зафиксирована в PRD, 235.5 остаётся `todo`.
2. Probe запускается через заданный Docker command, не выводит значения или
   секреты и для пилота печатает лишь имена полей и статусы.
3. `get_cassa_closes`, `get_payments`, `get_invoices` документируют и локально
   проверяют только подтверждённые поля.
4. `close_date` у `get_cassa_closes` не делает HTTP-request и сообщает `date`.
5. Data-модуль, probe-артефакт, unit/mock e2e, opt-in real suite и CI зелёные.
6. Regression покрывает named filters `get_payments`/`get_invoices` и runtime
   kill switch, а opt-in probe повторно получает HTTP 200 для каждого поля.
