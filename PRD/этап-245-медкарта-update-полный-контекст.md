# Этап 245. Надёжное обновление медкарты

## Цель

Сделать частичное обновление медкарты совместимым с предварительными проверками Vetmanager: перед PUT прочитать запись и передать неизменённые `patient_id`, `doctor_id`, `clinic_id` вместе с изменениями.

## Проверенные факты и границы

- `MedicalCardsController::doRestUpdate` проверяет эти три поля до внутреннего merge; на devtr6 частичный PUT дал 400, дополненный — 201.
- OpenAPI и `api_entity_reference-ru.md` подтверждают `/rest/api/MedicalCards`; `api_crud_permissions-ru.md` разрешает update.
- `AdmissionController::doRestUpdate` также проверяет тело до merge: `clinic_id`, `start`, `end`. Поэтому update admission сохраняет эти три значения после GET. Invoice и Hospital не определяют собственный `doRestUpdate` и используют базовый controller; аналогичной предполётной проверки в них не найдено.

## Декомпозиция

1. Написать mock-тест read-then-PUT и сохранения трёх полей.
2. Реализовать извлечение записи из ответа GET и отказать с понятной ошибкой, если обязательный контекст отсутствует.
3. Дополнить admission тем же read-before-write; проверить invoice/hospital как базовые controller paths.

## Архитектурное решение

Проблема локальна одному upstream controller. Выбран простой read-before-write прямо в `update_medical_card`, а не общий wrapper: у него один call-site и особый набор обязательных полей. Инвариант: значения, явно не меняемые MCP-инструментом, переносятся из текущей карты; PUT не выполняется с отсутствующим контекстом. Цена — один GET на обновление; rollback — удалить локальное дополнение, когда upstream исправит controller.

Architecture Critique: required (public write contract and an extra request).

## Критерии готовности

- PUT одного поля содержит три сохранённых ID.
- Неполный/невалидный GET не приводит к PUT.
- update admission/invoice/hospital остаются одним PUT без нового GET.
