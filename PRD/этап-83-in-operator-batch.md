# Этап 83. Оптимизация get_inactive_pets через IN оператор (retroactive PRD)

> **Ретроактивный PRD** — см. `AssumptionLog.md` раздел «Этап 83» для полной истории реализации.

## Цель

Устранить N+1 в `get_inactive_pets`. Текущий алгоритм делал 1-2 запроса на каждого питомца клиента (invoice + medcard). Real API подтвердил поддержку `IN` оператора с JSON-list value на `invoice.pet_id` и `MedicalCards.patient_id`.

## Scope

- Real API probe: `IN` работает на `invoice.pet_id`, `MedicalCards.patient_id`, `admission.status` с list value.
- Refactor `tools/_inactive_helpers.py::find_pets_at_client_last_visit`: один batched invoice запрос с `pet_id IN [ids]` + один batched medcard запрос для pets без invoice-матча.
- Регрессионный тест `test_get_inactive_pets_batches_invoice_and_medcard_via_in_operator`.

## Acceptance

- Latency=1.71s для 2 клиентов на devtr6 (раньше ~5-15s на 50).
- call_count=1 для invoice и medcard routes в regression тесте.
