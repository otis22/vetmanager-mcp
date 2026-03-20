# PRD: Этап 19. Инструменты для глобальных уведомлений `messages/*`

## Цель

Добавить MCP-инструменты для endpoint'ов глобальных уведомлений Vetmanager:

- `POST /rest/api/messages/all`
- `POST /rest/api/messages/users`
- `GET /rest/api/messages/reports`
- `POST /rest/api/messages/roles`

## Основания

- `artifacts/vetmanager_openapi_v6.json` содержит все четыре endpoint'а.
- `artifacts/vetmanager_postman_collection.json` подтверждает те же маршруты.
- Пользователь отдельно приложил рабочие примеры запросов и ожидаемых ответов.

## Решение

1. Реализовать инструменты в `tools/operations.py`, так как это операционный
   сценарий рассылок/уведомлений, а не сущность пациента или склада.
2. Для `reports` сохранить общий контракт list GET: `limit`, `offset`, `sort`,
   `filter`; дополнительно поддержать `campaign` из пользовательского примера.
3. Для `users` и `roles` ввести schema-ограничение `min_length=1`, чтобы MCP
   clients не передавали пустые списки адресатов.
4. Покрыть отправку mock/tool-level тестами; в real e2e добавить только безопасный
   smoke на `reports`, без побочных отправок сообщений.

## Подзадачи

- 19.1 Нормализовать этап 19 в `Roadmap.md` и создать PRD.
- 19.2 Реализовать `send_message_to_all`, `send_message_to_users`, `get_message_reports`, `send_message_to_roles`.
- 19.3 Добавить mock/tool-level тесты и безопасный real smoke для `reports`.
- 19.4 Обновить descriptions/README/AssumptionLog под новый контракт.
