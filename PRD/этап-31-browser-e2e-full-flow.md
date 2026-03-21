# PRD: Этап 31. Browser E2E полного сценария до MCP Bearer runtime

## Цель

Подтвердить в реальном браузере, что продуктовый сценарий работает сквозным
образом: web account -> Vetmanager integration -> Bearer token -> MCP runtime.

## Обязательная проверка

- регистрация account;
- login;
- сохранение active Vetmanager integration;
- выпуск Bearer token;
- реальный MCP вызов с этим Bearer token;
- проверка revoke/error path после web-действия.

## Что допускается

- Если login/password flow недоступен в текущем UI, это фиксируется как
  limitation, а browser E2E выполняется на доступном API-key flow.
- Результаты и ограничения обязательно попадают в `AssumptionLog.md` с
  абсолютным URL проверенного сценария.
