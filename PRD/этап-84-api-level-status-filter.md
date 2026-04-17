# Этап 84. API-level status IN в convenience tools (retroactive PRD)

> **Ретроактивный PRD** — см. `AssumptionLog.md` раздел «Этап 84» для полной истории.

## Цель

В этапе 81 `get_client_upcoming_visits` и `get_daily_schedule` фильтровали активные статусы client-side после `get_admissions` запроса. С подтверждённой в этапе 83 поддержкой `status IN [list]` — переходим на API-level фильтрацию.

## Scope

- Заменить client-side post-filter на API-level `status IN ACTIVE_ADMISSION_STATUSES` в обоих tools.
- Убрать поле `filtered_from_total` из ответа (envelope становится стабильным).
- Обновить тесты: `test_daily_schedule_filters_inactive_statuses_via_api` проверяет filter содержит `status IN`, response не содержит deleted/not_approved.

## Acceptance

- Real API verify на devtr6: `get_daily_schedule(date="2024-10-31")` возвращает 1 запись статус `delayed`, filter содержит `status IN [...]`.
- Точный `totalCount` (было: включал deleted/not_approved).
- Меньше данных по сети (API не возвращает фильтруемые строки).

## Breaking change

Поле `filtered_from_total` убрано из ответа. На момент этапа 84 stage 81 был в production <2 commita — вероятность поломки клиента нулевая.
