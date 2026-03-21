# PRD: Этап 22. Bearer auth в MCP runtime

## Цель

Перевести runtime-контракт MCP-сервера с `X-VM-Domain` / `X-VM-Api-Key` на
`Authorization: Bearer <service_token>`, используя storage foundation этапа 21
как источник account-based auth context.

## Проблема

- Текущий runtime всё ещё полностью привязан к headers-only Variant A.
- Storage, secret management и token lifecycle уже готовы, но runtime пока не
  умеет извлекать Bearer и связывать его с аккаунтом.
- Без поэтапного перевода легко сломать рабочий headers-only контур раньше,
  чем будут готовы lookup, ошибки и account-based credentials context.

## Границы этапа

- Этап 22 переводит runtime auth path.
- Шаг `22.1` ограничен только извлечением `Authorization: Bearer` из request.
- На `22.1` не выполняется lookup в БД и не удаляется headers-only fallback.
- Удаление `X-VM-*` поддержки переносится на `22.4`, когда lookup и ошибки уже
  будут реализованы.

## Декомпозиция

### 22.1 Извлечение Bearer
- Добавить отдельный request-layer helper для `Authorization: Bearer`.
- Поддержать безопасный разбор заголовка без утечки токена в ошибки.

### 22.2 Lookup токена
- Реализовать переход `service_bearer_token -> account -> active connection`.

### 22.3 Account-based auth context
- Заменить текущий credentials context на account-based runtime context.

### 22.4 Удаление `X-VM-*`
- Удалить runtime-поддержку `X-VM-Domain` / `X-VM-Api-Key`.

### 22.5 Ошибки Bearer runtime
- Ввести безопасные ошибки для missing/invalid/expired/revoked bearer.

### 22.6 Тесты
- Обновить unit/e2e тесты под bearer-only runtime-контракт.

## Критерии готовности для 22.1

- В проекте есть отдельный helper извлечения Bearer из HTTP request.
- Helper различает корректный `Authorization: Bearer ...` и невалидные формы.
- Текущее поведение headers-only runtime ещё не ломается до следующих шагов.
